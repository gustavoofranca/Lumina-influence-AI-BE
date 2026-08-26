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

    # Rate limit por agência em endpoints caros (in-memory, janela em segundos).
    RATE_LIMIT_ANALYZE: dict = {"limit": 20, "window": 60}
    RATE_LIMIT_REPORTS: dict = {"limit": 10, "window": 60}

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
