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
- **Tipo:** a checagem é por exclusão, não por lista de permitidos, pelo mesmo
  motivo de `media.py`: navegador e CDN mandam `application/octet-stream` para
  vídeo legítimo com frequência. O que se recusa é o que comprovadamente não é
  vídeo — HTML, JSON, texto.
- **Nome:** o nome enviado **nunca** toca o disco. O arquivo é gravado com UUID
  e a extensão derivada do tipo declarado. Nome de arquivo vindo do cliente é
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
from src.integrations.media import MAX_BYTES, MIMES_QUE_NAO_SAO_VIDEO, LocalFileFetcher
from src.models import AIAnalysis, Campaign, Influencer, Post, PostType, SocialAccount
from src.services.ai_analysis_service import analyze_post_multimodal
from src.utils.errors import ValidationError

logger = logging.getLogger(__name__)

# Extensão por tipo declarado. O dicionário existe para **não** usar a extensão
# que veio no nome do arquivo: ela é texto do cliente como qualquer outro.
EXTENSAO_POR_MIME = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "video/x-m4v": ".m4v",
    "application/octet-stream": ".mp4",
}


def storage_dir() -> Path:
    base = Path(current_app.root_path).parent / "storage" / "videos"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _validar_tipo(mime: str) -> str:
    limpo = (mime or "").split(";")[0].strip().lower()
    if limpo.startswith(MIMES_QUE_NAO_SAO_VIDEO):
        raise ValidationError(
            "O arquivo enviado não é um vídeo",
            details={"content_type": limpo},
        )
    return limpo or "video/mp4"


def _gravar(arquivo, mime: str) -> tuple[Path, int]:
    """Grava em disco com nome gerado, cortando se passar do teto."""
    destino = storage_dir() / f"{uuid.uuid4().hex}{EXTENSAO_POR_MIME.get(mime, '.mp4')}"
    escrito = 0
    try:
        with open(destino, "wb") as fh:
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

    if escrito == 0:
        destino.unlink(missing_ok=True)
        raise ValidationError("O arquivo enviado está vazio")
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

    mime = _validar_tipo(getattr(arquivo, "mimetype", None))
    caminho, tamanho = _gravar(arquivo, mime)
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
