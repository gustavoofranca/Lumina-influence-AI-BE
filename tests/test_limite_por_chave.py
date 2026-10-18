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


# --- memória: chaves vindas do cliente não podem se acumular -----------------
def test_conferir_chave_desconhecida_nao_cria_entrada(app):
    from src.utils import rate_limit as rl
    with app.test_request_context():
        conferir_limite(LOGIN, "nunca@x.com")
    assert f"{LOGIN}:nunca@x.com" not in rl._buckets


def test_chave_esvaziada_pela_poda_e_removida(app, monkeypatch):
    from src.utils import rate_limit as rl
    t = [1000.0]
    monkeypatch.setattr(rl.time, "monotonic", lambda: t[0])
    with app.test_request_context():
        registrar_tentativa(LOGIN, "a@x.com")
        t[0] += 901  # passou a janela de 15 min
        conferir_limite(LOGIN, "a@x.com")
    assert f"{LOGIN}:a@x.com" not in rl._buckets
    assert f"{LOGIN}:a@x.com" not in rl._janelas


def test_varredura_remove_chave_expirada_nunca_mais_tocada(app, monkeypatch):
    from src.utils import rate_limit as rl
    t = [1000.0]
    monkeypatch.setattr(rl.time, "monotonic", lambda: t[0])
    with app.test_request_context():
        registrar_tentativa(LOGIN, "aleatorio@x.com")   # nunca mais tocada
        limitar(FLUXO, "outro@x.com")                    # janela de 1 h, ainda viva
        t[0] += 901
        # Gravações suficientes para disparar a varredura periódica.
        for i in range(rl._VARRER_A_CADA):
            registrar_tentativa("RATE_LIMIT_CNPJ", f"ip{i}")
    assert f"{LOGIN}:aleatorio@x.com" not in rl._buckets
    assert f"{FLUXO}:outro@x.com" in rl._buckets


def test_reset_limpa_janelas(app):
    from src.utils import rate_limit as rl
    with app.test_request_context():
        registrar_tentativa(LOGIN, "a@x.com")
    rl.reset_rate_limits()
    assert not rl._buckets and not rl._janelas


def test_em_segundo_plano_erro_de_partial_nao_esconde_a_excecao(app, monkeypatch):
    import functools
    monkeypatch.setitem(app.config, "TESTING", False)
    from src.utils import segundo_plano as sp
    pronto = threading.Event()

    def falha(x):
        pronto.set()
        raise ValueError("boom")

    with app.app_context():
        sp.em_segundo_plano(functools.partial(falha, 1))
    assert pronto.wait(5)
