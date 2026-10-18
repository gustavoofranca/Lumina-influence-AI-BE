"""Envio de e-mail transacional.

Três destinos, escolhidos pelo ambiente:

- **Testes:** a mensagem vai para uma lista na app (`caixa_de_saida`), e a
  suíte confere o que foi "enviado" sem rede.
- **Sem SMTP configurado (desenvolvimento):** a mensagem vai para o log, com o
  link — é como se clica no link de verificação sem servidor de e-mail. O
  destinatário não entra no log (o log sai da fronteira de retenção do banco;
  ver `auth_service`). Produção não chega aqui: `ProdConfig` exige SMTP_HOST.
- **SMTP:** STARTTLS na 587, numa thread à parte. Falha vira log, não erro na
  tela: a resposta ao usuário já saiu, e ela é a mesma com ou sem e-mail.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from email.message import EmailMessage

from flask import current_app

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="lumina-email")
_CHAVE = "lumina_outbox"
_CAMPOS_SMTP = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM")


@dataclass(frozen=True)
class Mensagem:
    para: str
    assunto: str
    texto: str
    html: str


def caixa_de_saida(app=None) -> list[Mensagem]:
    app = app or current_app
    return app.extensions.setdefault(_CHAVE, [])


def enviar(msg: Mensagem) -> None:
    app = current_app._get_current_object()
    if app.testing:
        caixa_de_saida(app).append(msg)
        return
    # A thread não tem contexto da app: a configuração vai copiada.
    cfg = {campo: app.config.get(campo) for campo in _CAMPOS_SMTP}
    if not cfg["SMTP_HOST"]:
        logger.info("E-mail sem SMTP configurado — %s\n%s", msg.assunto, msg.texto)
        return
    _executor.submit(_enviar_smtp, cfg, msg)


def _montar(cfg: dict, msg: Mensagem) -> EmailMessage:
    # `EmailMessage` recusa cabeçalho com quebra de linha (ValueError): é o que
    # impede injeção de cabeçalho por um assunto ou destinatário malformado.
    mensagem = EmailMessage()
    mensagem["From"] = cfg.get("SMTP_FROM") or cfg.get("SMTP_USER") or ""
    mensagem["To"] = msg.para
    mensagem["Subject"] = msg.assunto
    mensagem.set_content(msg.texto)
    mensagem.add_alternative(msg.html, subtype="html")
    return mensagem


def _enviar_smtp(cfg: dict, msg: Mensagem) -> None:
    try:
        with smtplib.SMTP(cfg["SMTP_HOST"], int(cfg.get("SMTP_PORT") or 587), timeout=15) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if cfg.get("SMTP_USER"):
                smtp.login(cfg["SMTP_USER"], cfg.get("SMTP_PASSWORD") or "")
            smtp.send_message(_montar(cfg, msg))
    except Exception:
        logger.exception("Falha ao enviar e-mail (%s)", msg.assunto)
