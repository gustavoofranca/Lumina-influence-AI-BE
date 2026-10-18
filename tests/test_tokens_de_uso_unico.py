"""Tokens de uso único: guardados só como hash, vencem e não servem duas vezes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.extensions import db
from src.models import AuthToken, FinalidadeToken, User
from src.services import token_service as T
from src.utils.errors import BadRequestError

V, R = FinalidadeToken.VERIFICAR_EMAIL, FinalidadeToken.REDEFINIR_SENHA


def _user(conta):
    return db.session.get(User, conta.id)


def _codigo(exc) -> str:
    return exc.value.code


def test_emitir_e_consumir(app, conta_com_senha):
    with app.app_context():
        token = T.emitir(_user(conta_com_senha), V)
        assert T.consumir(token, V).id == conta_com_senha.id
        db.session.commit()


def test_banco_guarda_so_o_hash(app, conta_com_senha):
    with app.app_context():
        token = T.emitir(_user(conta_com_senha), V)
        registro = db.session.scalar(select(AuthToken))
        assert registro.token_hash != token and len(registro.token_hash) == 64


def test_segundo_uso_e_recusado(app, conta_com_senha):
    with app.app_context():
        token = T.emitir(_user(conta_com_senha), V)
        T.consumir(token, V)
        db.session.commit()
        with pytest.raises(BadRequestError) as exc:
            T.consumir(token, V)
        assert _codigo(exc) == "verification_token_invalid"


def test_ler_nao_consome(app, conta_com_senha):
    with app.app_context():
        token = T.emitir(_user(conta_com_senha), R)
        T.ler(token, R)
        assert T.consumir(token, R).id == conta_com_senha.id


def test_token_vencido(app, conta_com_senha):
    with app.app_context():
        token = T.emitir(_user(conta_com_senha), R)
        registro = db.session.scalar(select(AuthToken))
        registro.expira_em = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.session.commit()
        with pytest.raises(BadRequestError) as exc:
            T.consumir(token, R)
        assert _codigo(exc) == "reset_token_expired"


def test_finalidade_errada_nao_serve(app, conta_com_senha):
    with app.app_context():
        token = T.emitir(_user(conta_com_senha), V)
        with pytest.raises(BadRequestError) as exc:
            T.consumir(token, R)
        assert _codigo(exc) == "reset_token_invalid"


def test_emitir_de_novo_invalida_o_anterior(app, conta_com_senha):
    with app.app_context():
        antigo = T.emitir(_user(conta_com_senha), R)
        novo = T.emitir(_user(conta_com_senha), R)
        with pytest.raises(BadRequestError):
            T.consumir(antigo, R)
        assert T.consumir(novo, R).id == conta_com_senha.id


@pytest.mark.parametrize("lixo", ["", "x" * 500, None, 123])
def test_entrada_absurda_e_link_invalido(app, lixo):
    with app.app_context():
        with pytest.raises(BadRequestError) as exc:
            T.consumir(lixo, V)
        assert _codigo(exc) == "verification_token_invalid"
