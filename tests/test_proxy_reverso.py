"""Atrás do proxy reverso (Caddy), IP e esquema do cliente vêm de X-Forwarded-*.

Só quando `TRUSTED_PROXIES` diz quantos proxies há na frente. Sem proxy, quem
escreve o cabeçalho é o próprio cliente, e confiar nele deixaria qualquer um
escolher o IP e escapar do limite de tentativas por IP.
"""
from __future__ import annotations

import pytest
from flask import url_for

from src.app import create_app
from src.config import ProdConfig, TestConfig
from src.utils.rate_limit import ip_do_cliente

CABECALHOS = {
    "X-Forwarded-For": "203.0.113.7",
    "X-Forwarded-Proto": "https",
    "X-Forwarded-Host": "api.exemplo.com.br",
}


def _cliente(monkeypatch, proxies: int):
    monkeypatch.setattr(TestConfig, "TRUSTED_PROXIES", proxies)
    app = create_app("test")
    app.add_url_rule(
        "/_quem", "quem",
        lambda: {"ip": ip_do_cliente(), "url": url_for("quem", _external=True)},
    )
    return app.test_client()


def test_sem_proxy_configurado_o_cabecalho_do_cliente_e_ignorado(monkeypatch):
    dados = _cliente(monkeypatch, 0).get("/_quem", headers=CABECALHOS).get_json()
    assert dados["ip"] == "127.0.0.1"
    assert dados["url"].startswith("http://localhost/")


def test_atras_de_um_proxy_valem_o_ip_e_o_esquema_que_ele_repassa(monkeypatch):
    dados = _cliente(monkeypatch, 1).get("/_quem", headers=CABECALHOS).get_json()
    assert dados == {"ip": "203.0.113.7", "url": "https://api.exemplo.com.br/_quem"}


def test_ip_forjado_pelo_cliente_antes_do_proxy_nao_vale(monkeypatch):
    # O cliente manda o próprio X-Forwarded-For; o proxy acrescenta o IP real
    # no fim. Com um proxy confiável, só a última entrada conta.
    r = _cliente(monkeypatch, 1).get("/_quem", headers={"X-Forwarded-For": "1.2.3.4, 203.0.113.7"})
    assert r.get_json()["ip"] == "203.0.113.7"


def test_producao_exige_a_origem_do_front(monkeypatch):
    # Sem ela o CORS cairia no padrão localhost e o site publicado não
    # conseguiria falar com a API — falha silenciosa no navegador.
    for nome in ("DATABASE_URL", "JWT_SECRET", "FERNET_KEY", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"):
        monkeypatch.setenv(nome, "x")
    monkeypatch.delenv("FRONTEND_ORIGIN", raising=False)
    with pytest.raises(RuntimeError, match="FRONTEND_ORIGIN"):
        ProdConfig()
