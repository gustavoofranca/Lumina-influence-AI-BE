"""Parsing de body JSON via Pydantic, convertendo erros pro formato Lumina."""
from __future__ import annotations

from typing import TypeVar

from flask import request
from pydantic import BaseModel, ValidationError as PydanticValidationError

from src.utils.errors import ValidationError

T = TypeVar("T", bound=BaseModel)


def _simplify_errors(exc: PydanticValidationError) -> list[dict]:
    out = []
    for err in exc.errors():
        out.append(
            {
                "field": ".".join(str(p) for p in err.get("loc", ())),
                "message": err.get("msg", ""),
                "type": err.get("type", ""),
            }
        )
    return out


def parse_enum_arg(enum_cls, raw: str | None):
    """Converte uma query string em membro de enum. None se ausente. 422 se inválido."""
    if raw is None or raw == "":
        return None
    try:
        return enum_cls(raw)
    except ValueError as exc:
        valid = [e.value for e in enum_cls]
        raise ValidationError(
            f"Valor inválido para {enum_cls.__name__}",
            details={"received": raw, "valid": valid},
        ) from exc


def parse_json(schema_cls: type[T], *, partial: bool = False) -> T:
    """Valida o corpo JSON contra um schema Pydantic.

    `partial=True` ainda usa o mesmo schema — defina campos opcionais no schema
    de update. Levanta ValidationError (422) com detalhes por campo.
    """
    payload = request.get_json(silent=True)
    if payload is None:
        raise ValidationError("Corpo JSON ausente ou inválido", code="invalid_body")
    if not isinstance(payload, dict):
        raise ValidationError("Corpo JSON deve ser um objeto", code="invalid_body")
    try:
        return schema_cls.model_validate(payload)
    except PydanticValidationError as exc:
        raise ValidationError(
            "Erro de validação", details={"fields": _simplify_errors(exc)}
        ) from exc
