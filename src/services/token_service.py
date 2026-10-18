"""Tokens de uso único enviados por e-mail.

Três garantias:

- **Só o hash no banco.** O token cru existe no link do e-mail e em mais lugar
  nenhum.
- **Uso único de verdade.** `consumir` marca o uso com um UPDATE condicional
  (`WHERE usado_em IS NULL`) e só aceita se exatamente uma linha mudou. Dois
  cliques simultâneos no mesmo link não passam os dois.
- **Um válido por vez.** Emitir um token novo inutiliza os pendentes da mesma
  finalidade — pedir o link de novo invalida o que ficou na caixa de entrada.

A busca é pelo hash, em coluna indexada: o tempo da consulta não revela nada
sobre o token, então não há comparação a fazer em tempo constante.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from src.extensions import db
from src.models import AuthToken, FinalidadeToken, User
from src.utils.errors import BadRequestError

VALIDADE = {
    FinalidadeToken.VERIFICAR_EMAIL: timedelta(hours=24),
    FinalidadeToken.REDEFINIR_SENHA: timedelta(minutes=30),
}
_PREFIXO = {
    FinalidadeToken.VERIFICAR_EMAIL: "verification_token",
    FinalidadeToken.REDEFINIR_SENHA: "reset_token",
}
_MENSAGEM = {
    "invalid": "Este link é inválido ou já foi usado.",
    "expired": "Este link venceu. Peça um novo.",
}
_TAMANHO_MAXIMO = 200


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _utc(momento: datetime) -> datetime:
    # SQLite (testes) devolve sem fuso; o valor gravado é UTC.
    return momento.replace(tzinfo=timezone.utc) if momento.tzinfo is None else momento


def _erro(finalidade: FinalidadeToken, tipo: str) -> BadRequestError:
    return BadRequestError(_MENSAGEM[tipo], code=f"{_PREFIXO[finalidade]}_{tipo}")


def emitir(user: User, finalidade: FinalidadeToken) -> str:
    agora = _agora()
    db.session.execute(
        update(AuthToken)
        .where(
            AuthToken.user_id == user.id,
            AuthToken.finalidade == finalidade,
            AuthToken.usado_em.is_(None),
        )
        .values(usado_em=agora)
    )
    token = secrets.token_urlsafe(32)
    db.session.add(AuthToken(
        user_id=user.id, finalidade=finalidade, token_hash=_hash(token),
        expira_em=agora + VALIDADE[finalidade],
    ))
    db.session.commit()
    return token


def _registro_valido(token, finalidade: FinalidadeToken) -> AuthToken:
    if not isinstance(token, str) or not token or len(token) > _TAMANHO_MAXIMO:
        raise _erro(finalidade, "invalid")
    registro = db.session.scalar(
        select(AuthToken).where(
            AuthToken.token_hash == _hash(token), AuthToken.finalidade == finalidade
        )
    )
    if registro is None or registro.usado_em is not None:
        raise _erro(finalidade, "invalid")
    if _utc(registro.expira_em) < _agora():
        raise _erro(finalidade, "expired")
    return registro


def _dono(registro: AuthToken, finalidade: FinalidadeToken) -> User:
    user = db.session.get(User, registro.user_id)
    if user is None or user.deleted_at is not None:
        raise _erro(finalidade, "invalid")
    return user


def ler(token: str, finalidade: FinalidadeToken) -> User:
    """Confere o token sem gastá-lo — para validar o resto do pedido antes."""
    return _dono(_registro_valido(token, finalidade), finalidade)


def consumir(token: str, finalidade: FinalidadeToken) -> User:
    """Gasta o token e devolve o dono. O commit fica com quem chama."""
    registro = _registro_valido(token, finalidade)
    resultado = db.session.execute(
        update(AuthToken)
        .where(AuthToken.id == registro.id, AuthToken.usado_em.is_(None))
        .values(usado_em=_agora())
        .execution_options(synchronize_session=False)
    )
    if resultado.rowcount != 1:
        db.session.rollback()
        raise _erro(finalidade, "invalid")
    return _dono(registro, finalidade)
