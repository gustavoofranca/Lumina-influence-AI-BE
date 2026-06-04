"""Configuração da aplicação Lumina BE.

Quatro ambientes: Dev / Test / Staging / Prod.
Variáveis sensíveis nunca têm default — em produção falha cedo se faltar.
"""
from __future__ import annotations

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

    # IA
    GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY")

    # Front-end
    FRONTEND_ORIGIN: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")

    # Base usada pra montar os redirect_uri do OAuth. Deve bater EXATAMENTE com o
    # que está registrado no provider (Google/Microsoft). Se None, usa o host da request.
    OAUTH_REDIRECT_BASE: str | None = os.getenv("OAUTH_REDIRECT_BASE")

    # Scheduler
    SCHEDULER_API_ENABLED: bool = False
    SCHEDULER_TIMEZONE: str = "America/Sao_Paulo"


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


class StagingConfig(Config):
    ENV = "staging"
    DEBUG = False

    @classmethod
    def from_env(cls) -> "StagingConfig":
        cls.SQLALCHEMY_DATABASE_URI = _required("DATABASE_URL")
        cls.JWT_SECRET = _required("JWT_SECRET")
        return cls()


class ProdConfig(Config):
    ENV = "prod"
    DEBUG = False
    TESTING = False

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
