"""Configuração da aplicação Lumina BE.

Quatro ambientes: Dev / Test / Staging / Prod.
Variáveis sensíveis nunca têm default — em produção falha cedo se faltar.
"""
from __future__ import annotations

import base64
import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Variável de ambiente obrigatória ausente: {name}")
    return value


class Config:
    """Base — defaults seguros pra dev. Subclasses sobrescrevem em prod."""

    ENV: str = "base"
    DEBUG: bool = False
    TESTING: bool = False
    VERSION: str = "0.1.0"

    # Banco
    SQLALCHEMY_DATABASE_URI: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/lumina_dev",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    SQLALCHEMY_ENGINE_OPTIONS: dict = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

    # JWT
    JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-jwt-secret-change-me")
    JWT_ACCESS_TTL: timedelta = timedelta(hours=1)
    JWT_REFRESH_TTL: timedelta = timedelta(days=30)

    # OAuth
    GOOGLE_CLIENT_ID: str | None = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET: str | None = os.getenv("GOOGLE_CLIENT_SECRET")
    MICROSOFT_CLIENT_ID: str | None = os.getenv("MICROSOFT_CLIENT_ID")
    MICROSOFT_CLIENT_SECRET: str | None = os.getenv("MICROSOFT_CLIENT_SECRET")

    # Criptografia de tokens das APIs sociais
    FERNET_KEY: str | None = os.getenv("FERNET_KEY")

    # Credenciais das APIs sociais (B8). YouTube cai pra GOOGLE_* se não setado.
    META_CLIENT_ID: str | None = os.getenv("META_CLIENT_ID")
    META_CLIENT_SECRET: str | None = os.getenv("META_CLIENT_SECRET")
    TIKTOK_CLIENT_KEY: str | None = os.getenv("TIKTOK_CLIENT_KEY")
    TIKTOK_CLIENT_SECRET: str | None = os.getenv("TIKTOK_CLIENT_SECRET")
    YOUTUBE_CLIENT_ID: str | None = os.getenv("YOUTUBE_CLIENT_ID")
    YOUTUBE_CLIENT_SECRET: str | None = os.getenv("YOUTUBE_CLIENT_SECRET")

    # IA
    GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
    GEMINI_TIMEOUT_SECONDS: int = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "90"))
    # Máximo de comentários enviados no prompt (controle de custo/contexto)
    GEMINI_MAX_COMMENTS: int = int(os.getenv("GEMINI_MAX_COMMENTS", "30"))
    # Sobrecarga do Google (503 "high demand") é temporária e por modelo. Antes
    # a primeira falha ia direto para a tela; agora insiste e, esgotadas as
    # tentativas, cai no modelo de reserva. A análise registra qual dos dois
    # respondeu. Crédito na conta não evita o 503 — só isto ajuda.
    GEMINI_FALLBACK_MODEL: str | None = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash")
    GEMINI_RETRIES: int = int(os.getenv("GEMINI_RETRIES", "2"))
    GEMINI_RETRY_BACKOFF_SECONDS: float = float(os.getenv("GEMINI_RETRY_BACKOFF_SECONDS", "3"))
    # No free tier o Google pode usar o conteúdo enviado para melhorar seus
    # produtos; no tier pago, não. A Política de Privacidade publicada afirma
    # que os dados **não** são usados para treinar modelo, então rodar em free
    # tier fora de desenvolvimento contradiz um compromisso com o usuário.
    # Não há como descobrir o tier pela chave: é declaração explícita, e o boot
    # reclama alto quando ela falta onde importa.
    GEMINI_PAID_TIER: bool = os.getenv("GEMINI_PAID_TIER", "").lower() in ("1", "true", "yes")

    # Retenção de registro técnico (dias). A política de privacidade publicada
    # declara este prazo ao usuário: mudar o número aqui muda um compromisso.
    RETENTION_DAYS: int = int(os.getenv("RETENTION_DAYS", "90"))

    # Front-end
    FRONTEND_ORIGIN: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")

    # Base usada pra montar os redirect_uri do OAuth. Deve bater EXATAMENTE com o
    # que está registrado no provider (Google/Microsoft). Se None, usa o host da request.
    OAUTH_REDIRECT_BASE: str | None = os.getenv("OAUTH_REDIRECT_BASE")

    # Se setado, o callback OAuth REDIRECIONA pra essa URL do front com os tokens
    # no fragmento (#access_token=...). Se None, retorna JSON (modo API/teste).
    AUTH_SUCCESS_REDIRECT: str | None = os.getenv("AUTH_SUCCESS_REDIRECT")
    # Habilita POST /auth/dev-login (atalho de login local sem OAuth). Off em prod.
    DEV_LOGIN_ENABLED: bool = os.getenv("DEV_LOGIN_ENABLED", "true").lower() == "true"

    # Habilita o provedor OAuth local que substitui Instagram e TikTok enquanto
    # não há app aprovado nas plataformas (ver `src/integrations/demo.py`). Off
    # em staging e produção pelo mesmo motivo do `dev-login`: é atalho de
    # desenvolvimento, e fora de dev ele produziria conexão que não coleta nada
    # real. O roteador só cai no provedor local quando a credencial verdadeira
    # da plataforma está ausente — configurar a credencial desliga o atalho
    # sozinho, sem depender de ninguém lembrar desta variável.
    DEMO_SOCIAL_ENABLED: bool = os.getenv("DEMO_SOCIAL_ENABLED", "true").lower() == "true"

    # Teto do corpo da requisição. O Flask recusa com 413 antes de ler o
    # restante do fluxo, então o custo de um corpo gigante para no soquete e
    # não na memória do processo.
    #
    # 1 MB é folgado de propósito. Nenhum endpoint recebe arquivo — não existe
    # `request.files` no projeto, o vídeo é baixado pelo servidor em
    # `integrations/media.py`, não enviado pelo cliente. O maior corpo legítimo
    # é a criação de campanha: cerca de 600 bytes por participante (UUID,
    # cachê e entregáveis de até 500 caracteres), o que dá 60 KB para uma
    # campanha de cem influenciadores. O teto deixa folga de mais de mil
    # participantes e ainda corta pela raiz o corpo abusivo.
    MAX_CONTENT_LENGTH: int = int(os.getenv("MAX_CONTENT_LENGTH_BYTES", str(1024 * 1024)))

    # Rate limit por agência em endpoints caros (in-memory, janela em segundos).
    RATE_LIMIT_ANALYZE: dict = {"limit": 20, "window": 60}
    RATE_LIMIT_REPORTS: dict = {"limit": 10, "window": 60}
    # A prévia monta o mesmo contexto que o PDF — 10 consultas e cerca de dois
    # segundos, medidos em 09/09 — e só não grava arquivo. Ficava sem limite
    # nenhum, e aberta a qualquer papel, enquanto a geração ao lado era limitada
    # e restrita a admin e membro: a proteção guardava a porta cara e deixava a
    # vizinha aberta.
    #
    # Orçamento próprio, e mais folgado que o da geração: a prévia é mais barata
    # e é interativa — o assistente a refaz ao voltar um passo e mudar seção ou
    # período. Trinta por minuto cobre isso com sobra e ainda corta o abuso.
    RATE_LIMIT_REPORT_PREVIEW: dict = {"limit": 30, "window": 60}

    # Quantas publicações cada sync traz por conta. Era 10 fixo no código, o
    # que bastava para demonstrar e era pouco para auditar: um criador com
    # trezentas publicações tinha três por cento delas analisadas.
    #
    # Cada publicação custa uma chamada de comentários além da listagem, então
    # subir isso sem limite transforma um clique em centenas de requisições à
    # plataforma — daí ser configuração, e não um número maior chutado.
    SYNC_POSTS_LIMIT: int = int(os.getenv("SYNC_POSTS_LIMIT", "25"))

    # IDs de post na plataforma que a coleta pula, separados por vírgula.
    # Fica no ambiente e não no código: é decisão sobre conteúdo de uma pessoa
    # específica, não regra do produto.
    SYNC_POSTS_IGNORADOS: frozenset = frozenset(
        p.strip() for p in os.getenv("SYNC_POSTS_IGNORADOS", "").split(",") if p.strip()
    )

    # Scheduler
    SCHEDULER_API_ENABLED: bool = False
    SCHEDULER_TIMEZONE: str = "America/Sao_Paulo"
    # coalesce: junta execuções perdidas em uma só; misfire_grace_time: tolerância.
    SCHEDULER_JOB_DEFAULTS: dict = {
        "coalesce": True,
        "max_instances": 1,
        "misfire_grace_time": 3600,
    }


class DevConfig(Config):
    ENV = "dev"
    DEBUG = True


class TestConfig(Config):
    """Configuração da suíte. Todo literal aqui é fictício, por decisão.

    Exceção registrada a SEC-04 (auditoria de 08/09/2026): a regra pede que
    valor de credencial exista apenas em `.env.example`, com marcador. Os
    literais desta classe contrariam a letra e não o propósito — nenhum casa
    prefixo de credencial real (`GOCSPX-`, `AIza`, `sk-`, `ya29.`, `ghp_`,
    `AKIA`), e todos começam por `test-` justamente para serem inconfundíveis.

    Estarem fixos aqui, e não vindos do ambiente, é o que garante que a suíte
    rode igual em qualquer máquina — ver o comentário de `AUTH_SUCCESS_REDIRECT`
    logo abaixo, onde a variável de ambiente já mudou o comportamento do teste
    conforme o `.env` do desenvolvedor.
    """

    ENV = "test"
    TESTING = True
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "TEST_DATABASE_URL", "sqlite:///:memory:"
    )
    JWT_SECRET = "test-secret-com-32-bytes-no-minimo-pra-hs256"
    FRONTEND_ORIGIN = "http://localhost:5173"
    GOOGLE_CLIENT_ID = "test-google-client-id"
    GOOGLE_CLIENT_SECRET = "test-google-client-secret"
    MICROSOFT_CLIENT_ID = "test-ms-client-id"
    MICROSOFT_CLIENT_SECRET = "test-ms-client-secret"
    OAUTH_REDIRECT_BASE = "http://localhost:5000"
    # Fixo em None: com a variável setada no .env do desenvolvedor, o callback
    # passa a redirecionar em vez de responder JSON e a suíte muda de
    # comportamento conforme a máquina em que roda. Quem quiser exercitar o
    # redirect sobrescreve a config no próprio teste.
    AUTH_SUCCESS_REDIRECT = None
    # Nunca usa a key real do .env em testes — força mock/NotConfigured.
    GEMINI_API_KEY = None
    # A suíte exercita a nova tentativa sem esperar de verdade.
    GEMINI_RETRY_BACKOFF_SECONDS = 0
    # Fernet key fixa e válida (32 bytes → base64), independente do .env.
    FERNET_KEY = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode()
    # Credenciais de teste pras plataformas sociais (adapters montam auth URL).
    META_CLIENT_ID = "test-meta-id"
    META_CLIENT_SECRET = "test-meta-secret"
    TIKTOK_CLIENT_KEY = "test-tiktok-key"
    TIKTOK_CLIENT_SECRET = "test-tiktok-secret"


class StagingConfig(Config):
    ENV = "staging"
    DEBUG = False
    DEV_LOGIN_ENABLED = False  # atalho de login vale só em dev e nos testes
    DEMO_SOCIAL_ENABLED = False  # provedor social local, idem

    @classmethod
    def from_env(cls) -> "StagingConfig":
        cls.SQLALCHEMY_DATABASE_URI = _required("DATABASE_URL")
        cls.JWT_SECRET = _required("JWT_SECRET")
        return cls()


class ProdConfig(Config):
    ENV = "prod"
    DEBUG = False
    TESTING = False
    DEV_LOGIN_ENABLED = False  # nunca habilita atalho de login em produção
    DEMO_SOCIAL_ENABLED = False  # nem provedor social de demonstração

    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "")
    JWT_SECRET = os.getenv("JWT_SECRET", "")

    def __init__(self) -> None:
        # Em prod, sem defaults inseguros — valida no boot.
        for name in ("DATABASE_URL", "JWT_SECRET", "FERNET_KEY"):
            if not os.getenv(name):
                raise RuntimeError(
                    f"Variável de ambiente obrigatória ausente em produção: {name}"
                )


CONFIG_MAP: dict[str, type[Config]] = {
    "dev": DevConfig,
    "test": TestConfig,
    "staging": StagingConfig,
    "prod": ProdConfig,
}


def get_config(name: str | None = None) -> type[Config]:
    name = (name or os.getenv("FLASK_ENV") or "dev").lower()
    return CONFIG_MAP.get(name, DevConfig)
