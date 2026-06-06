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
