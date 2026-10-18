"""Login por senha e o ciclo de vida da senha.

O login responde a mesma coisa — mesma mensagem, mesmo status, mesmo tempo —
para e-mail inexistente, conta excluída, conta só com Google e senha errada
(OWASP; spec, seção 7). Só quem acerta a senha de uma conta ainda não
verificada fica sabendo que precisa confirmar o e-mail: saber a senha já prova
que a conta é dela.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.extensions import db
from src.integrations.email import enviar
from src.models import FinalidadeToken, User
from src.services import emails, token_service, user_service
from src.services.auth_service import invalidar_sessoes
from src.utils.errors import ForbiddenError, UnauthorizedError
from src.utils.rate_limit import (
    conferir_limite,
    ip_do_cliente,
    limitar,
    registrar_tentativa,
    zerar,
)
from src.utils.segundo_plano import em_segundo_plano
from src.utils.senha import (
    conferir,
    conferir_contra_hash_ficticio,
    gerar_hash,
    precisa_rehash,
    problema_da_senha,
)
from src.utils.validation import erro_de_campo

logger = logging.getLogger(__name__)

CREDENCIAIS_INVALIDAS = "E-mail ou senha incorretos."
_POR_IP, _POR_EMAIL = "RATE_LIMIT_LOGIN_IP", "RATE_LIMIT_LOGIN_EMAIL"


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def entrar(email: str, senha: str) -> User:
    """Confere a credencial. `email` já chega em minúsculas (tipo `Email`)."""
    ip = ip_do_cliente()
    conferir_limite(_POR_IP, ip)
    conferir_limite(_POR_EMAIL, email)

    user = user_service.find_by_email(email)
    if user is None or user.deleted_at is not None or not user.password_hash:
        conferir_contra_hash_ficticio(senha)
        valida = False
    else:
        valida = conferir(senha, user.password_hash)

    if not valida:
        registrar_tentativa(_POR_IP, ip)
        registrar_tentativa(_POR_EMAIL, email)
        raise UnauthorizedError(CREDENCIAIS_INVALIDAS, code="invalid_credentials")

    zerar(_POR_EMAIL, email)
    if precisa_rehash(user.password_hash):
        user.password_hash = gerar_hash(senha)
        db.session.commit()
    if user.email_verificado_em is None:
        raise ForbiddenError("Confirme seu e-mail antes de entrar.", code="email_not_verified")
    return user


def esqueci_senha(email: str) -> None:
    em_segundo_plano(_processar_esqueci, email)


def _processar_esqueci(email: str) -> None:
    # Também serve a quem entra só pelo Google: é o caminho de "Definir senha",
    # e o link no e-mail prova que a pessoa é dona do endereço.
    user = user_service.find_by_email(email)
    if user is not None and user.deleted_at is None:
        enviar(emails.redefinicao(user, token_service.emitir(user, FinalidadeToken.REDEFINIR_SENHA)))


def redefinir_senha(token: str, senha: str) -> None:
    # Lê antes de consumir: senha recusada pela política não pode gastar o link.
    user = token_service.ler(token, FinalidadeToken.REDEFINIR_SENHA)
    problema = problema_da_senha(senha, email=user.email, nome=user.name)
    if problema:
        raise erro_de_campo("password", problema, "password_policy")
    user = token_service.consumir(token, FinalidadeToken.REDEFINIR_SENHA)
    user.password_hash = gerar_hash(senha)
    if user.email_verificado_em is None:
        # Quem abriu o link provou que é dona do e-mail.
        user.email_verificado_em = _agora()
    invalidar_sessoes(user)
    db.session.commit()
    logger.info("Senha redefinida pelo link para o usuário %s", user.id)


def trocar_senha(user: User, atual: str, nova: str) -> User:
    limitar("RATE_LIMIT_TROCA_SENHA", str(user.id))
    # 422 no campo, e não 401: o front lê 401 como sessão expirada e
    # deslogaria a pessoa por ela ter digitado errado.
    if not user.password_hash:
        raise erro_de_campo(
            "current_password", 'sua conta ainda não tem senha — use "Definir senha"', "no_password"
        )
    if not conferir(atual, user.password_hash):
        raise erro_de_campo("current_password", "senha atual incorreta", "invalid_current_password")
    problema = problema_da_senha(nova, email=user.email, nome=user.name)
    if problema:
        raise erro_de_campo("new_password", problema, "password_policy")
    user.password_hash = gerar_hash(nova)
    invalidar_sessoes(user)
    db.session.commit()
    logger.info("Senha trocada pelo próprio usuário %s", user.id)
    return user


def definir_senha_por_admin(email: str, senha: str) -> None:
    """Usado pelo comando `flask users set-password`. Levanta ValueError com a frase do erro."""
    user = user_service.find_by_email(email)
    if user is None or user.deleted_at is not None:
        raise ValueError("usuário não encontrado")
    problema = problema_da_senha(senha, email=user.email, nome=user.name)
    if problema:
        raise ValueError(f"a senha {problema}")
    user.password_hash = gerar_hash(senha)
    if user.email_verificado_em is None:
        user.email_verificado_em = _agora()
    invalidar_sessoes(user)
    db.session.commit()
    logger.info("Senha definida por comando para o usuário %s", user.id)


def aceitar_termos(user: User) -> None:
    if user.termos_aceitos_em is None:
        user.termos_aceitos_em = _agora()
        db.session.commit()
