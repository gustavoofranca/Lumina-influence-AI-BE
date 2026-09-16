"""Provedor de demonstração das redes sociais — Instagram e TikTok sem app aprovado.

Por que existe
--------------
Instagram e TikTok só coletam com app de desenvolvedor aprovado na plataforma:
a Meta exige verificação de negócio e App Review (fila de duas a quatro semanas,
ver `docs/meta-app-review.md`), e o TikTok exige app fora do sandbox com
redirect em HTTPS público. Nenhuma das duas é obtível sob demanda, e sem elas o
caminho inteiro — consentimento, troca de código, cifragem do token, coleta,
normalização, análise — ficava sem como ser exercido fora dos testes de unidade,
que substituem o adaptador por mock e portanto não exercem o fluxo.

Este módulo põe um provedor **local** no lugar da plataforma. O que ele
substitui é exatamente uma coisa: o servidor do outro lado da rede. Todo o
restante é o código de produção, sem desvio — o mesmo `handle_callback`, o mesmo
`state` de uso único, a mesma cifragem Fernet do token, o mesmo `_real_sync`
gravando `Post` e comentário a partir de `NormalizedPost`.

O que ele não faz
-----------------
Não se apresenta como dado real. A conta conectada por aqui carrega
`connection_mode == "demo"` no payload da API, e a interface rotula. É a mesma
regra da ADR-003 numa outra forma: se o sistema não sabe, ele diz que não sabe —
e aqui ele sabe que o que mostra não veio da plataforma.

Vale só em dev e na suíte: `DEMO_SOCIAL_ENABLED` é fixo em `False` nas
configurações de staging e produção, igual ao `DEV_LOGIN_ENABLED`, e o roteador
de adaptadores só chega aqui quando a credencial real **também** está ausente.
Credencial configurada tem precedência sempre: o provedor real nunca é
substituído por este.
"""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from flask import current_app, url_for

from src.integrations.base import (
    NormalizedComment,
    NormalizedPost,
    OAuthTokenBundle,
    ProfileMetrics,
    SocialAdapter,
    TokenRevokedError,
)
from src.models import PostType

# Prefixo do token emitido aqui. Serve a dois propósitos: o adaptador recusa
# token que não seja seu (um token real chegando a este adaptador é sintoma de
# configuração trocada, não algo para engolir em silêncio), e qualquer inspeção
# do banco distingue conexão de demonstração de conexão real sem precisar
# consultar a configuração do ambiente.
TOKEN_PREFIX = "demo"
CODE_PREFIX = "demo-code"
# Separador do código emitido pela tela de consentimento, que carrega qual conta
# consentiu: `demo-code:instagram:anapsouza`. O provedor real identifica a conta
# porque o código é dele; aqui o código precisa dizer, e sem isso o adaptador
# devolvia sempre o mesmo handle genérico — o pareamento de `handle_callback` é
# por (criador, plataforma, handle), então cada conexão criava uma conta
# paralela à que o criador já tinha, e o total de seguidores somava as duas.
CODE_SEP = ":"

# Validade longa de propósito: a conexão precisa sobreviver à apresentação, e a
# expiração de token já é exercida pelos testes do caminho real.
TOKEN_TTL = timedelta(days=30)

_HANDLES = {
    "instagram": "criador.demo",
    "tiktok": "criador.demo",
}

# Legendas no formato que cada plataforma produz: o Instagram traz legenda com
# hashtag, o TikTok traz título curto de vídeo.
_LEGENDAS = {
    "instagram": [
        "Bastidores da campanha de primavera #publi #parceria",
        "Três formas de usar a peça nova — qual é a sua? #moda",
        "Cheguei nos 50 mil! Obrigada por cada comentário",
        "Resenha honesta: usei por duas semanas antes de falar #publi",
        "Rotina de skincare simplificada, com o que sobrou da nécessaire",
        "Perguntas e respostas: o que ninguém conta sobre criar conteúdo",
        "Look do evento de ontem. Detalhe do sapato no carrossel",
        "Dia de gravação com a equipe #bastidores",
    ],
    "tiktok": [
        "3 erros que eu cometia no começo",
        "POV: a encomenda chegou antes do combinado",
        "Testando o produto que todo mundo pediu #publi",
        "Respondendo ao comentário mais curtido",
        "Antes e depois em 15 segundos",
        "Tutorial de 30 segundos que salvou meu dia",
        "Bastidores do que não foi pro feed",
        "A parte 2 que vocês pediram",
    ],
}

# Corpus com mistura deliberada: elogio genuíno, crítica, pergunta, e o padrão
# de comentário automatizado (genérico, emoji solto, chamada para outro perfil).
# A análise de IA é o objeto do trabalho — alimentar o modelo só com elogio
# produziria sentimento uniforme e probabilidade de bot perto de zero, o que não
# demonstra medição nenhuma.
_COMENTARIOS_GENUINOS = [
    "amei o look, onde comprou a saia?",
    "finalmente alguém falando a verdade sobre esse produto",
    "usei sua dica e funcionou demais, obrigada!",
    "confesso que achei caro pelo que entrega",
    "esse tom de batom fica perfeito em você",
    "faz um vídeo mais longo explicando a parte 2?",
    "não gostei dessa parceria, esperava mais",
    "que edição linda, qual app você usa?",
    "comprei por sua indicação e chegou rápido",
    "achei o conteúdo repetitivo dessa vez, sem graça",
    "a iluminação desse vídeo tá impecável",
    "alguém mais achou que o preço não vale?",
    "você é a única que mostra o antes e depois de verdade",
    "pode falar do tamanho? fiquei em dúvida entre P e M",
    "esse foi o melhor conteúdo da semana, parabéns",
]

_COMENTARIOS_AUTOMATIZADOS = [
    "top top top",
    "lindaaaa demais",
    "segue de volta",
    "conteúdo top! visita meu perfil",
    "maravilhosa",
    "GANHE SEGUIDORES no link da bio",
    "amei amei amei",
    "quer crescer no digital? chama no direct",
]

_AUTORES = [
    "ana.reis", "marcos_lima", "juliacosta", "pedro.almeida", "bia__santos",
    "rafa.oliveira", "carla.mendes", "lucas.ferreira", "user8823911",
    "digital.growth.br", "perfil_novo_2026", "tatiane.rocha",
]


def _rng(*partes: str) -> random.Random:
    """RNG determinístico a partir das partes.

    Determinismo importa mais que variedade aqui: a mesma conta sincronizada
    duas vezes tem que devolver os mesmos posts, senão cada sync criaria dez
    posts novos e a contagem cresceria sem limite. É o contrato de
    `platform_post_id` estável que as APIs reais oferecem.
    """
    semente = hashlib.sha256("|".join(partes).encode()).hexdigest()[:16]
    return random.Random(int(semente, 16))


class DemoAdapter(SocialAdapter):
    """Adaptador que fala com um provedor local em vez da plataforma."""

    def __init__(self, platform: str) -> None:
        self.platform = platform

    # ------------------------------------------------------------------ OAuth
    def build_auth_url(self, *, state: str, redirect_uri: str) -> str:
        """URL da tela de consentimento local.

        `_external=True` porque o destino é navegação do browser, como no
        provedor real: o usuário sai da aplicação, consente, e volta.
        """
        base = url_for("demo_oauth.authorize", platform=self.platform, _external=True)
        return base + "?" + urlencode({"state": state, "redirect_uri": redirect_uri})

    def exchange_code(self, *, code: str, redirect_uri: str) -> OAuthTokenBundle:
        if not code.startswith(CODE_PREFIX):
            # Código de provedor real chegando aqui é configuração trocada.
            # Aceitá-lo emitiria token de demonstração para um consentimento
            # verdadeiro, o contrário do que este módulo existe para fazer.
            raise TokenRevokedError(
                self.platform + ": código não veio do provedor de demonstração",
                details={"motivo": "codigo_de_outro_provedor"},
            )
        handle = self._handle_do_codigo(code)
        r = _rng(self.platform, "perfil", handle)
        return OAuthTokenBundle(
            access_token="%s.%s.%012x" % (TOKEN_PREFIX, self.platform, r.getrandbits(48)),
            refresh_token="%s.refresh.%s" % (TOKEN_PREFIX, self.platform),
            expires_at=datetime.now(timezone.utc) + TOKEN_TTL,
            platform_user_id="%s-%s-%08x" % (TOKEN_PREFIX, self.platform, r.getrandbits(32)),
            handle=handle,
            follower_count=self._seguidores(r),
        )

    def _handle_do_codigo(self, code: str) -> str:
        """Extrai do código qual conta consentiu; cai no padrão se não vier."""
        partes = code.split(CODE_SEP)
        if len(partes) >= 3 and partes[2]:
            return partes[2]
        return _HANDLES[self.platform]

    def refresh(self, refresh_token: str) -> OAuthTokenBundle:
        self._exigir_token_proprio(refresh_token)
        r = _rng(self.platform, "perfil")
        return OAuthTokenBundle(
            access_token="%s.%s.%012x" % (TOKEN_PREFIX, self.platform, r.getrandbits(48)),
            refresh_token=refresh_token,
            expires_at=datetime.now(timezone.utc) + TOKEN_TTL,
        )

    # ----------------------------------------------------------------- Coleta
    def fetch_profile_metrics(self, access_token: str) -> ProfileMetrics:
        self._exigir_token_proprio(access_token)
        r = _rng(self.platform, "perfil")
        return ProfileMetrics(
            follower_count=self._seguidores(r),
            handle=_HANDLES[self.platform],
            platform_user_id="%s-%s-%08x" % (TOKEN_PREFIX, self.platform, r.getrandbits(32)),
        )

    def fetch_recent_posts(self, access_token: str, limit: int = 10) -> list[NormalizedPost]:
        self._exigir_token_proprio(access_token)
        agora = datetime.now(timezone.utc)
        posts: list[NormalizedPost] = []

        for i, legenda in enumerate(_LEGENDAS[self.platform][:limit]):
            r = _rng(self.platform, "post", str(i))
            alcance = r.randint(4_000, 48_000)
            # Engajamento como fração do alcance, na faixa que se observa em
            # conta média — e não número solto, que produziria post com mais
            # curtida que alcance.
            curtidas = int(alcance * r.uniform(0.03, 0.11))
            comentarios = int(curtidas * r.uniform(0.01, 0.06))
            if self.platform == "tiktok":
                tipo = PostType.VIDEO
            else:
                tipo = PostType.REEL if i % 3 == 0 else PostType.IMAGE
            eh_video = tipo in (PostType.REEL, PostType.VIDEO)

            posts.append(NormalizedPost(
                platform_post_id="%s_%s_%02d" % (TOKEN_PREFIX, self.platform, i),
                post_type=tipo,
                posted_at=agora - timedelta(days=3 * i + r.randint(0, 2), hours=r.randint(0, 23)),
                caption=legenda,
                # Sem endereço de mídia inventado: URL que não resolve produz
                # miniatura quebrada na tela, e foi por isso que o seed parou de
                # inventar a dele (commit 017f5fc).
                video_url=None,
                thumbnail_url=None,
                reach_total=alcance,
                # A divisão entre orgânico e pago não é concedida pelas APIs sem
                # programa comercial (ADR-005): os adaptadores reais põem todo o
                # alcance em orgânico e zero em pago, e este faz igual.
                reach_organic=alcance,
                reach_paid=0,
                impressions=int(alcance * r.uniform(1.05, 1.6)),
                likes=curtidas,
                comments_count=comentarios,
                shares=int(curtidas * r.uniform(0.01, 0.08)),
                saves=int(curtidas * r.uniform(0.02, 0.15)),
                avg_watch_time=round(r.uniform(4.5, 26.0), 1) if eh_video else None,
                retention_rate=round(r.uniform(0.28, 0.72), 3) if eh_video else None,
            ))
        return posts

    def fetch_post_insights(self, access_token: str, platform_post_id: str) -> dict:
        self._exigir_token_proprio(access_token)
        r = _rng(self.platform, "insights", platform_post_id)
        return {
            "reach": r.randint(4_000, 48_000),
            "views": r.randint(5_000, 60_000),
            "source": "demo",
        }

    def fetch_post_comments(
        self, access_token: str, platform_post_id: str, limit: int = 15
    ) -> list[NormalizedComment]:
        self._exigir_token_proprio(access_token)
        r = _rng(self.platform, "comentarios", platform_post_id)
        agora = datetime.now(timezone.utc)

        # A proporção de automatizado varia por post, entre um quinto e um
        # terço: fração fixa faria toda análise devolver a mesma probabilidade
        # de bot, e número que nunca varia não demonstra medição.
        quantos = min(limit, r.randint(8, 15))
        n_bot = max(1, int(quantos * r.uniform(0.18, 0.34)))
        escolhidos = (
            r.sample(_COMENTARIOS_AUTOMATIZADOS, min(n_bot, len(_COMENTARIOS_AUTOMATIZADOS)))
            + r.sample(_COMENTARIOS_GENUINOS, min(quantos - n_bot, len(_COMENTARIOS_GENUINOS)))
        )
        r.shuffle(escolhidos)

        return [
            NormalizedComment(
                platform_comment_id="%s_c%02d" % (platform_post_id, i),
                content=texto,
                posted_at=agora - timedelta(hours=r.randint(1, 72), minutes=r.randint(0, 59)),
                author_handle=r.choice(_AUTORES),
                like_count=r.randint(0, 180),
            )
            for i, texto in enumerate(escolhidos)
        ]

    # --------------------------------------------------------------- Interno
    def _exigir_token_proprio(self, token: str) -> None:
        if not (token or "").startswith(TOKEN_PREFIX + "."):
            raise TokenRevokedError(
                self.platform + ": token não foi emitido pelo provedor de demonstração",
                details={"motivo": "token_de_outro_provedor"},
            )

    def _seguidores(self, r: random.Random) -> int:
        return r.randint(18_000, 240_000)


def habilitado() -> bool:
    """O provedor de demonstração está disponível neste ambiente?"""
    return bool(current_app.config.get("DEMO_SOCIAL_ENABLED"))
