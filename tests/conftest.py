"""Fixtures comuns dos testes."""
from __future__ import annotations

import pytest

from src.app import create_app
from src.extensions import db as _db


@pytest.fixture(scope="session")
def app():
    app = create_app("test")
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """Zera os buckets de rate limit antes de cada teste (são module-global)."""
    from src.utils.rate_limit import reset_rate_limits

    reset_rate_limits()
    yield


@pytest.fixture()
def db_session(app):
    """Sessão de banco com rollback no fim do teste."""
    with app.app_context():
        connection = _db.engine.connect()
        transaction = connection.begin()
        _db.session.begin_nested()
        yield _db.session
        _db.session.rollback()
        transaction.rollback()
        connection.close()


SENHA_DE_TESTE = "café com pão de queijo"


class _Conta:
    pass


@pytest.fixture()
def conta_com_senha(app):
    """Agência + admin verificado com senha. Some no fim, com tudo o que pendurar nele."""
    from datetime import datetime, timezone

    from src.models import Agency, User, UserRole
    from src.utils.senha import gerar_hash

    with app.app_context():
        agencia = Agency(name="Agência da Conta", cnpj="11.222.333/0001-81")
        user = User(
            email="conta@agencia.com.br", name="Conta Teste", role=UserRole.ADMIN,
            agency=agencia, password_hash=gerar_hash(SENHA_DE_TESTE),
            email_verificado_em=datetime.now(timezone.utc),
        )
        _db.session.add_all([agencia, user])
        _db.session.commit()
        c = _Conta()
        c.id, c.agency_id, c.email, c.senha = user.id, agencia.id, user.email, SENHA_DE_TESTE
    yield c
    with app.app_context():
        restante = _db.session.get(Agency, c.agency_id)
        if restante is not None:
            _db.session.delete(restante)
            _db.session.commit()


@pytest.fixture()
def outbox(app):
    """E-mails "enviados" durante o teste, na ordem."""
    from src.integrations.email import caixa_de_saida

    caixa = caixa_de_saida(app)
    caixa.clear()
    yield caixa
    caixa.clear()
