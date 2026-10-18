"""Os e-mails transacionais da autenticação.

Os links usam `FRONTEND_ORIGIN` da configuração, **nunca** o host da
requisição: montado a partir do cabeçalho `Host`, um atacante pediria a
redefinição da senha de outra pessoa com `Host: site-dele`, e o link legítimo,
com o token, iria parar no servidor dele (*reset poisoning*).
"""
from __future__ import annotations

from html import escape
from urllib.parse import urlencode

from flask import current_app

from src.integrations.email import Mensagem


def _link(caminho: str, token: str | None = None) -> str:
    base = current_app.config["FRONTEND_ORIGIN"].rstrip("/")
    return f"{base}{caminho}" + (f"?{urlencode({'token': token})}" if token else "")


def _html(paragrafos: list[str], botao: tuple[str, str] | None = None) -> str:
    corpo = "".join(f"<p>{escape(p)}</p>" for p in paragrafos)
    if botao:
        rotulo, url = botao
        corpo += (
            f'<p><a href="{escape(url)}" style="display:inline-block;padding:12px 20px;'
            f'background:#7c3aed;color:#fff;border-radius:8px;text-decoration:none">'
            f"{escape(rotulo)}</a></p>"
            f'<p style="font-size:12px;color:#666">Se o botão não abrir, copie: {escape(url)}</p>'
        )
    return f'<div style="font-family:Arial,sans-serif;font-size:15px;color:#111">{corpo}</div>'


def verificacao(user, token: str) -> Mensagem:
    link = _link("/verificar-email", token)
    linhas = [
        f"Olá, {user.name}.",
        "Confirme seu e-mail para ativar sua conta na Lumina.",
        "O link vale por 24 horas. Se não foi você quem se cadastrou, ignore este e-mail.",
    ]
    return Mensagem(
        para=user.email,
        assunto="Confirme seu e-mail — Lumina",
        texto="\n\n".join(linhas[:2] + [link] + linhas[2:]),
        html=_html(linhas, ("Confirmar e-mail", link)),
    )


def conta_existente(email: str) -> Mensagem:
    entrar, recuperar = _link("/login"), _link("/recuperar-senha")
    linhas = [
        "Alguém tentou criar uma conta na Lumina com este e-mail, que já tem conta.",
        f"Para entrar: {entrar}",
        f"Esqueceu a senha? {recuperar}",
        "Se não foi você, nada muda na sua conta e você pode ignorar este e-mail.",
    ]
    return Mensagem(
        para=email, assunto="Você já tem uma conta na Lumina",
        texto="\n\n".join(linhas), html=_html(linhas),
    )


def cnpj_em_uso(email: str, cnpj: str) -> Mensagem:
    linhas = [
        f"Recebemos um cadastro com o CNPJ {cnpj}, que já tem conta na Lumina.",
        "Para entrar na conta da agência, peça um convite ao administrador dela.",
        "Se você acredita que o CNPJ foi cadastrado por engano, responda este e-mail.",
    ]
    return Mensagem(
        para=email, assunto="Este CNPJ já tem conta na Lumina",
        texto="\n\n".join(linhas), html=_html(linhas),
    )


def redefinicao(user, token: str) -> Mensagem:
    link = _link("/redefinir-senha", token)
    linhas = [
        f"Olá, {user.name}.",
        "Recebemos um pedido para criar uma nova senha para sua conta na Lumina.",
        "O link vale por 30 minutos e só pode ser usado uma vez. Se não foi você, ignore "
        "este e-mail: sua senha atual continua valendo.",
    ]
    return Mensagem(
        para=user.email,
        assunto="Redefinir sua senha — Lumina",
        texto="\n\n".join(linhas[:2] + [link] + linhas[2:]),
        html=_html(linhas, ("Criar nova senha", link)),
    )
