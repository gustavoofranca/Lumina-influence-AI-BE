"""Limite de tentativas por IP, e-mail ou usuário, e trabalho fora da requisição."""
from __future__ import annotations

import threading

import pytest

from src.utils.rate_limit import (
    RateLimitExceeded,
    conferir_limite,
    ip_do_cliente,
    limitar,
    registrar_tentativa,
    zerar,
)
from src.utils.segundo_plano import em_segundo_plano

FLUXO = "RATE_LIMIT_EMAIL_FLOW_EMAIL"   # 3 por hora
LOGIN = "RATE_LIMIT_LOGIN_EMAIL"        # 5 por 15 min


def test_limitar_conta_cada_chamada(app):
    with app.test_request_context():
        for _ in range(3):
            limitar(FLUXO, "a@x.com")
        with pytest.raises(RateLimitExceeded) as exc:
            limitar(FLUXO, "a@x.com")
    assert exc.value.details["retry_after_seconds"] > 0
    assert "Muitas tentativas" in exc.value.message


def test_conferir_sozinho_nao_registra(app):
    with app.test_request_context():
        for _ in range(20):
            conferir_limite(LOGIN, "a@x.com")


def test_falhas_registradas_bloqueiam_a_conferencia(app):
    with app.test_request_context():
        for _ in range(5):
            registrar_tentativa(LOGIN, "a@x.com")
        with pytest.raises(RateLimitExceeded):
            conferir_limite(LOGIN, "a@x.com")


def test_zerar_libera(app):
    with app.test_request_context():
        for _ in range(5):
            registrar_tentativa(LOGIN, "a@x.com")
        zerar(LOGIN, "a@x.com")
        conferir_limite(LOGIN, "a@x.com")


def test_chaves_sao_independentes(app):
    with app.test_request_context():
        for _ in range(3):
            limitar(FLUXO, "a@x.com")
        limitar(FLUXO, "b@x.com")


def test_ip_do_cliente(app):
    with app.test_request_context(environ_base={"REMOTE_ADDR": "203.0.113.9"}):
        assert ip_do_cliente() == "203.0.113.9"


def test_em_segundo_plano_roda_na_hora_durante_os_testes(app):
    chamadas = []
    with app.app_context():
        em_segundo_plano(chamadas.append, 1)
    assert chamadas == [1]


def test_em_segundo_plano_fora_dos_testes_tem_contexto_da_app(app, monkeypatch):
    monkeypatch.setitem(app.config, "TESTING", False)
    pronto, visto = threading.Event(), {}

    def tarefa():
        from flask import current_app
        visto["env"] = current_app.config["ENV"]
        pronto.set()

    with app.app_context():
        em_segundo_plano(tarefa)
    assert pronto.wait(5)
    assert visto["env"] == "test"
