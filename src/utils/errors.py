"""Exceções customizadas do domínio Lumina."""
from __future__ import annotations


class LuminaError(Exception):
    """Base de todos os erros de negócio. Tem code, message e details."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(
        self,
        message: str = "Erro interno",
        details: dict | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if code:
            self.code = code

    def to_dict(self) -> dict:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }


class ValidationError(LuminaError):
    status_code = 422
    code = "validation_error"


class NotFoundError(LuminaError):
    status_code = 404
    code = "not_found"


class UnauthorizedError(LuminaError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(LuminaError):
    status_code = 403
    code = "forbidden"


class ConflictError(LuminaError):
    status_code = 409
    code = "conflict"
