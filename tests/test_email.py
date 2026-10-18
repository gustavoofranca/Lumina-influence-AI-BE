"""Envio de e-mail e os modelos transacionais."""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from src.integrations import email as email_mod
from src.integrations.email import Mensagem, enviar
from src.services import emails

CFG = {
    "SMTP_HOST": "smtp.gmail.com", "SMTP_PORT": 587, "SMTP_USER": "eu@gmail.com",
    "SMTP_PASSWORD": "senha-de-app", "SMTP_FROM": "Lumina <eu@gmail.com>",
}
MSG = Mensagem("ana@x.com", "Assunto", "corpo do e-mail", "<p>corpo</p>")


class _SmtpFalso:
    ultima = None

    def __init__(self, host, port, timeout):
        self.host, self.port, self.passos = host, port, []
        _SmtpFalso.ultima = self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self, context):
        self.passos.append("starttls")

    def login(self, usuario, senha):
        self.passos.append(("login", usuario))

    def send_message(self, mensagem):
        self.passos.append(("send", mensagem["To"], mensagem["Subject"]))


def test_durante_os_testes_vai_para_a_caixa_de_saida(app, outbox):
    with app.app_context():
        enviar(MSG)
    assert outbox == [MSG]


def test_smtp_usa_starttls_login_e_envia(monkeypatch):
    monkeypatch.setattr(email_mod.smtplib, "SMTP", _SmtpFalso)
    email_mod._enviar_smtp(CFG, MSG)
    s = _SmtpFalso.ultima
    assert (s.host, s.port) == ("smtp.gmail.com", 587)
    assert s.passos == ["starttls", ("login", "eu@gmail.com"), ("send", "ana@x.com", "Assunto")]


def test_falha_de_smtp_vira_log_e_nao_excecao(monkeypatch, caplog):
    def _quebra(*args, **kwargs):
        raise OSError("rede fora")

    monkeypatch.setattr(email_mod.smtplib, "SMTP", _quebra)
    email_mod._enviar_smtp(CFG, MSG)
    assert "Falha ao enviar e-mail" in caplog.text


def test_sem_smtp_vai_para_o_log_sem_o_destinatario(app, monkeypatch, caplog):
    monkeypatch.setitem(app.config, "TESTING", False)
    monkeypatch.setitem(app.config, "SMTP_HOST", None)
    with app.app_context(), caplog.at_level(logging.INFO):
        enviar(MSG)
    assert "corpo do e-mail" in caplog.text
    assert "ana@x.com" not in caplog.text


def test_sem_smtp_fora_do_debug_nao_loga_o_token(app, monkeypatch, caplog):
    # `app.debug` lê config["DEBUG"]; é essa chave que o teste desliga.
    monkeypatch.setitem(app.config, "TESTING", False)
    monkeypatch.setitem(app.config, "DEBUG", False)
    monkeypatch.setitem(app.config, "SMTP_HOST", None)
    assert app.debug is False
    msg = Mensagem("ana@x.com", "Assunto sigiloso", "abra /x?token=SEGREDO123", "<p>h</p>")
    with app.app_context(), caplog.at_level(logging.INFO):
        enviar(msg)
    assert "Assunto sigiloso" in caplog.text
    assert "SEGREDO123" not in caplog.text
    assert "ana@x.com" not in caplog.text


def test_quebra_de_linha_no_assunto_e_recusada():
    with pytest.raises(ValueError):
        email_mod._montar(CFG, Mensagem("a@x.com", "Oi\nBcc: alvo@y.com", "t", "h"))


def test_links_usam_frontend_origin_e_nunca_o_host_da_requisicao(app):
    with app.test_request_context(base_url="http://atacante.example"):
        m = emails.verificacao(SimpleNamespace(name="Ana", email="ana@x.com"), "tok123")
    assert "http://localhost:5173/verificar-email?token=tok123" in m.texto
    assert "atacante" not in m.texto + m.html


def test_nome_e_escapado_no_html(app):
    with app.app_context():
        m = emails.redefinicao(SimpleNamespace(name="<script>", email="a@x.com"), "t")
    assert "<script>" not in m.html and "&lt;script&gt;" in m.html


def test_os_quatro_modelos(app):
    pessoa = SimpleNamespace(name="Ana", email="ana@x.com")
    with app.app_context():
        assuntos = [
            emails.verificacao(pessoa, "t").assunto,
            emails.conta_existente("ana@x.com").assunto,
            emails.cnpj_em_uso("ana@x.com", "11.222.333/0001-81").assunto,
            emails.redefinicao(pessoa, "t").assunto,
        ]
    assert assuntos == [
        "Confirme seu e-mail — Lumina",
        "Você já tem uma conta na Lumina",
        "Este CNPJ já tem conta na Lumina",
        "Redefinir sua senha — Lumina",
    ]
