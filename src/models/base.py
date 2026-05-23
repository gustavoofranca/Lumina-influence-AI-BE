"""Base declarativa + mixins reutilizáveis.

Padrão SQLAlchemy 2.x com `DeclarativeBase` e `Mapped[]`.
A `Base` definida aqui é registrada no Flask-SQLAlchemy via `extensions.py`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, JSON, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class Base(DeclarativeBase):
    """Base declarativa única do projeto."""


# JSON portável: JSONB no Postgres, JSON em SQLite (testes).
JSONField = JSON().with_variant(JSONB(), "postgresql")


class TimestampMixin:
    """`created_at` e `updated_at` automáticos via banco."""

    @declared_attr
    def created_at(cls) -> Mapped[datetime]:
        return mapped_column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        )

    @declared_attr
    def updated_at(cls) -> Mapped[datetime]:
        return mapped_column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        )


class SoftDeleteMixin:
    """`deleted_at` nullable — quando preenchido, o registro está logicamente apagado."""

    @declared_attr
    def deleted_at(cls) -> Mapped[Optional[datetime]]:
        return mapped_column(DateTime(timezone=True), nullable=True, default=None)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
