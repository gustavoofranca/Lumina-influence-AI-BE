"""A configuração da suíte não pode reciclar a conexão do SQLite em memória."""
from __future__ import annotations

from src.config import TestConfig


def test_suite_nao_recicla_a_conexao_do_banco_em_memoria():
    # Com SQLite em memória, a conexão É o banco: reciclá-la abre um banco novo
    # e vazio, e todo teste depois disso falha com "no such table".
    assert "pool_recycle" not in TestConfig.SQLALCHEMY_ENGINE_OPTIONS
