"""Recebe um vídeo enviado pela interface e roda a análise multimodal sobre ele.

Por que existe
--------------
O `HttpVideoFetcher` baixa o vídeo de `post.video_url`, que é o desenho certo
para o caminho de produção: na vida real a mídia mora na CDN da plataforma e
chega pela conta conectada. Só que isso deixava a análise multimodal inalcançável
para quem **tem o arquivo** e ainda não tem a conta conectada — que é o caso de
demonstrar o produto, e o de auditar um vídeo que a agência recebeu por fora.

Este módulo é a porta de entrada desse arquivo. Ele grava a mídia, cria o post
e chama `analyze_post_multimodal` passando um `LocalFileFetcher`: a análise em
si, o envio ao modelo, a validação do JSON e a persistência continuam sendo o
caminho único de sempre.

Onde estão os limites
---------------------
Upload é a superfície de ataque mais clássica que existe, e aqui ela é a única
do sistema — nenhum outro endpoint recebe arquivo. O que guarda esta porta:

- **Tamanho:** o teto global de corpo (`MAX_CONTENT_LENGTH`, 1 MB) continua
  valendo para a API inteira; só esta rota o eleva, por requisição. Quem faz
  isso é o endpoint, não a configuração — afrouxar o teto global protegeria
  menos todos os outros 55 endpoints para servir a um.
- **Tipo:** lido na assinatura dos primeiros bytes, por lista de permitidos —
  MP4, MOV e WebM. O tipo declarado não decide nada: é texto do cliente como o
  nome, e navegador manda `application/octet-stream` para vídeo legítimo com
  frequência. Até 15/10/2026 a checagem era uma lista de bloqueio sobre o tipo
  declarado, e um HTML enviado como `video/mp4` era gravado e ia ao modelo.
- **Nome:** o nome enviado **nunca** toca o disco. O arquivo é gravado com UUID
  e a extensão derivada do conteúdo. Nome de arquivo vindo do cliente é
  travessia de diretório esperando acontecer.
- **Escopo:** o influencer é resolvido por `get_scoped_or_404`, então uma agência
  não consegue anexar vídeo ao criador de outra.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import current_app

from src.extensions import db
from src.integrations.media import MAX_BYTES, LocalFileFetcher
from src.models import AIAnalysis, Campaign, Influencer, Post, PostType, SocialAccount
from src.services.ai_analysis_service import analyze_post_multimodal
from src.utils.errors import ValidationError
from src.utils.validation import erro_de_campo

logger = logging.getLogger(__name__)

# Extensão por tipo detectado. O dicionário existe para **não** usar a extensão
# que veio no nome do arquivo: ela é texto do cliente como qualquer outro.
EXTENSAO_POR_MIME = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
}

# Quanto do começo do arquivo a detecção lê. O cabeçalho EBML do WebM declara o
# formato (`DocType`) nos primeiros ~40 bytes.
TAMANHO_DA_ASSINATURA = 64

# MP4 e MOV são caixas ISO: tamanho em 4 bytes, depois o nome da caixa. O
# arquivo moderno começa por `ftyp`, seguido da marca; o QuickTime antigo
# começa direto num destes átomos.
_ATOMOS_QUICKTIME_ANTIGO = {b"moov", b"mdat", b"wide", b"free", b"skip", b"pnot"}
# Marcas que usam a mesma caixa `ftyp` e não são vídeo: foto HEIF/AVIF (a do
# iPhone), RAW da Canon e áudio M4A.
_MARCAS_QUE_NAO_SAO_VIDEO = {
    b"heic", b"heix", b"heim", b"heis", b"mif1", b"msf1", b"avif", b"avis",
    b"crx ", b"M4A ", b"M4B ", b"M4P ",
}
_EBML = b"\x1a\x45\xdf\xa3"

MENSAGEM_FORMATO = "não é um vídeo em formato aceito (envie MP4, MOV ou WebM)"


def storage_dir() -> Path:
    base = Path(current_app.root_path).parent / "storage" / "videos"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _tipo_pelo_conteudo(inicio: bytes) -> str | None:
    """Tipo do vídeo pela assinatura nos primeiros bytes, ou None se não for aceito."""
    caixa, marca = inicio[4:8], inicio[8:12]
    if caixa == b"ftyp":
        if marca in _MARCAS_QUE_NAO_SAO_VIDEO:
            return None
        return "video/quicktime" if marca == b"qt  " else "video/mp4"
    if caixa in _ATOMOS_QUICKTIME_ANTIGO:
        return "video/quicktime"
    # Matroska usa o mesmo cabeçalho EBML e declara `matroska` no lugar de
    # `webm`; o modelo não aceita esse formato.
    if inicio.startswith(_EBML) and b"webm" in inicio:
        return "video/webm"
    return None


def _ler_tipo(arquivo) -> tuple[str, bytes]:
    """Lê o começo do arquivo e devolve o tipo detectado e os bytes já lidos."""
    inicio = arquivo.read(TAMANHO_DA_ASSINATURA)
    if not inicio:
        raise ValidationError("O arquivo enviado está vazio")
    mime = _tipo_pelo_conteudo(inicio)
    if mime is None:
        raise erro_de_campo("video", MENSAGEM_FORMATO)
    return mime, inicio


def _gravar(arquivo, mime: str, inicio: bytes) -> tuple[Path, int]:
    """Grava em disco com nome gerado, cortando se passar do teto.

    `inicio` são os bytes que a detecção de tipo já leu do arquivo.
    """
    destino = storage_dir() / f"{uuid.uuid4().hex}{EXTENSAO_POR_MIME[mime]}"
    escrito = len(inicio)
    try:
        with open(destino, "wb") as fh:
            fh.write(inicio)
            while True:
                pedaco = arquivo.read(1024 * 256)
                if not pedaco:
                    break
                escrito += len(pedaco)
                if escrito > MAX_BYTES:
                    raise ValidationError(
                        "Vídeo excede o tamanho máximo permitido",
                        details={"max_mb": MAX_BYTES // (1024 * 1024)},
                    )
                fh.write(pedaco)
    except Exception:
        # Arquivo pela metade não fica no disco: ele não serve para nada e
        # ocuparia espaço sem nenhum post apontando para ele.
        destino.unlink(missing_ok=True)
        raise
    return destino, escrito


def _data_do_post(campanha: Campaign | None) -> datetime:
    """Dentro do período da campanha, quando houver uma.

    Um vídeo anexado a uma campanha precisa cair na janela que o relatório
    promete na capa; gravá-lo com a data de hoje o deixaria fora do próprio
    relatório para o qual foi enviado.
    """
    if campanha is None:
        return datetime.now(timezone.utc)
    inicio = datetime.combine(
        campanha.period_start, datetime.min.time()
    ).replace(tzinfo=timezone.utc)
    fim = datetime.combine(
        campanha.period_end, datetime.min.time()
    ).replace(tzinfo=timezone.utc)
    agora = datetime.now(timezone.utc)
    if inicio <= agora <= fim:
        return agora
    # Fora da janela, ancora no primeiro dia dela — e não na borda exata, que
    # é onde comparação de data costuma escorregar.
    return min(inicio + timedelta(days=1), fim)


def analisar_video_enviado(
    *,
    influencer: Influencer,
    agency_id: uuid.UUID,
    arquivo,
    caption: str | None = None,
    campaign_id: uuid.UUID | None = None,
) -> tuple[Post, AIAnalysis]:
    """Grava o vídeo, cria o post e roda a análise multimodal sobre ele."""
    conta = db.session.query(SocialAccount).filter_by(influencer_id=influencer.id).first()
    if conta is None:
        raise ValidationError(
            "O criador precisa de uma conta social para receber a publicação",
            details={"influencer_id": str(influencer.id)},
        )

    campanha = None
    if campaign_id is not None:
        campanha = db.session.query(Campaign).filter_by(
            id=campaign_id, agency_id=agency_id
        ).first()
        if campanha is None:
            raise ValidationError("Campanha não encontrada nesta agência")

    mime, inicio = _ler_tipo(arquivo)
    caminho, tamanho = _gravar(arquivo, mime, inicio)
    logger.info(
        "Vídeo recebido: influencer=%s bytes=%d mime=%s", influencer.id, tamanho, mime
    )

    post = Post(
        social_account_id=conta.id,
        campaign_id=campanha.id if campanha is not None else None,
        platform_post_id=f"upload-{uuid.uuid4().hex[:12]}",
        post_type=PostType.VIDEO,
        posted_at=_data_do_post(campanha),
        caption=(caption or "").strip() or None,
        # Aponta para o arquivo guardado, e não para uma URL de rede: quem lê
        # este campo depois precisa saber que a mídia é local.
        video_url=f"file://storage/videos/{caminho.name}",
    )
    db.session.add(post)
    db.session.flush()

    try:
        analise = analyze_post_multimodal(
            post,
            agency_id=agency_id,
            video_fetcher=LocalFileFetcher(str(caminho), mime),
        )
    except Exception:
        # A análise falhou: o post ficaria no histórico do criador como uma
        # publicação que ele não fez, e o arquivo sem nada apontando para ele.
        db.session.rollback()
        caminho.unlink(missing_ok=True)
        raise

    db.session.commit()
    return post, analise
