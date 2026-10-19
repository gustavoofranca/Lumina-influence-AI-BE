"""Pydantic schemas usados nos endpoints de /auth."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Optional

from pydantic import (
    BaseModel, ConfigDict, EmailStr, Field, StrictBool, StrictStr, StringConstraints,
    ValidationInfo, field_validator,
)

from src.schemas.campos import CnpjObrigatorio, Email, NomeDeEmpresa, NomeDePessoa
from src.utils.senha import problema_da_senha


class UserOut(BaseModel):
    """Representação pública de um usuário autenticado. Nunca inclui o hash."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    name: str
    avatar_url: Optional[str] = None
    oauth_provider: Optional[str] = None
    role: str
    agency_id: Optional[uuid.UUID] = None
    has_password: bool = False
    email_verified: bool = False
    terms_accepted: bool = False
    created_at: datetime


class AgencySummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    # O front usa para levar o admin sem CNPJ ao primeiro acesso.
    cnpj: Optional[str] = None


class TokenPairOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in_seconds: int = Field(..., description="TTL do access token")


class LoginCallbackOut(BaseModel):
    """Resposta do /auth/<provider>/callback."""

    user: UserOut
    agency: Optional[AgencySummaryOut] = None
    tokens: TokenPairOut


class MeOut(BaseModel):
    user: UserOut
    agency: Optional[AgencySummaryOut] = None


class CnpjConsultaIn(BaseModel):
    cnpj: CnpjObrigatorio


# Teto só para não processar corpo absurdo; a regra de verdade é a política.
SenhaDigitada = Annotated[StrictStr, StringConstraints(max_length=1024)]
Token = Annotated[StrictStr, StringConstraints(min_length=1, max_length=200)]


class RegisterIn(BaseModel):
    """Cadastro por e-mail e senha. Sem `role`: quem se cadastra é admin da agência nova."""

    model_config = ConfigDict(extra="forbid")

    # A ordem importa: `name` e `email` são validados antes de `password`, que
    # os usa para recusar senha montada com dado da própria pessoa.
    name: NomeDePessoa(160)
    email: Email
    password: SenhaDigitada
    agency_name: NomeDeEmpresa(160)
    cnpj: CnpjObrigatorio
    accept_terms: StrictBool

    @field_validator("password")
    @classmethod
    def _politica(cls, valor: str, info: ValidationInfo) -> str:
        problema = problema_da_senha(valor, email=info.data.get("email"), nome=info.data.get("name"))
        if problema:
            raise ValueError(problema)
        return valor

    @field_validator("accept_terms")
    @classmethod
    def _termos(cls, valor: bool) -> bool:
        if valor is not True:
            raise ValueError("aceite os Termos de Uso e a Política de Privacidade")
        return valor


class EmailIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: Email


SenhaInformada = Annotated[StrictStr, StringConstraints(min_length=1, max_length=1024)]


class VerifyEmailIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: Token
    # Obrigatória para conta criada com senha (conferida no serviço, que sabe
    # de quem é o token); convite sem senha confirma só com o link.
    password: Optional[SenhaInformada] = None


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: Email
    # Sem política aqui: quem entra digita a senha que já tem.
    password: SenhaInformada


class ResetPasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: Token
    # A política é conferida no serviço: ela precisa do e-mail e do nome do
    # dono do token, que este schema não conhece.
    password: SenhaDigitada


class ChangePasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: SenhaInformada
    new_password: SenhaDigitada
