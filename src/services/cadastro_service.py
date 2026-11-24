"""Cadastro por e-mail e senha, verificação do e-mail e reenvio do link.

Enumeração de contas (spec, seção 7): o cadastro responde o mesmo 202 para
e-mail novo, e-mail já cadastrado e CNPJ já em uso — quem fica sabendo o que
aconteceu é o dono do e-mail, pela mensagem que chega. Tudo o que difere entre
esses ramos roda em segundo plano, para o tempo de resposta também não contar.

A situação do CNPJ na Receita é a exceção que responde 422 na hora, e por isso
é conferida antes de olhar o e-mail: depende só do CNPJ, que é público.

Pré-sequestro (spec, seção 7): o link de confirmação de uma conta criada com
senha só a ativa com essa senha. Sem isso, quem recadastrasse o e-mail de outra
pessoa depois dela — e antes do clique — ativaria, pelo link mais novo que chega
à vítima, uma conta com a senha do atacante.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.extensions import db
from src.integrations.brasilapi import consultar_cnpj
from src.integrations.email import enviar
from src.models import Agency, FinalidadeToken, User, UserRole
from src.schemas.auth import RegisterIn
from src.services import emails, token_service, user_service
from src.utils.errors import BadRequestError
from src.utils.rate_limit import conferir_limite, ip_do_cliente, registrar_tentativa, zerar
from src.utils.segundo_plano import em_segundo_plano
from src.utils.senha import conferir, gerar_hash
from src.utils.validation import erro_de_campo

logger = logging.getLogger(__name__)

MENSAGEM_LINK_ENVIADO = "Enviamos um link de confirmação para o seu e-mail."
MENSAGEM_SE_HOUVER_CONTA = "Se houver uma conta com este e-mail, enviamos um link."
# Mesmo orçamento do login: é a mesma senha sendo adivinhada.
_POR_IP, _POR_EMAIL = "RATE_LIMIT_LOGIN_IP", "RATE_LIMIT_LOGIN_EMAIL"


def conferir_situacao_do_cnpj(cnpj: str) -> None:
    consulta = consultar_cnpj(cnpj)
    if consulta.impeditiva:
        raise erro_de_campo(
            "cnpj", f"este CNPJ está {consulta.situacao} na Receita Federal", "cnpj_inactive"
        )


def _enviar_verificacao(user: User) -> None:
    enviar(emails.verificacao(user, token_service.emitir(user, FinalidadeToken.VERIFICAR_EMAIL)))


def cadastrar(dados: RegisterIn) -> None:
    """Valida o que pode ser dito na hora; o resto vai para segundo plano."""
    conferir_situacao_do_cnpj(dados.cnpj)
    em_segundo_plano(_processar_cadastro, dados)


def _processar_cadastro(dados: RegisterIn) -> None:
    existente = user_service.find_by_email(dados.email)
    if existente is not None:
        pendente = existente.deleted_at is None and existente.email_verificado_em is None
        if pendente and existente.password_hash:
            # Pré-sequestro de conta (spec, seção 7): um cadastro pendente não
            # guarda dado nenhum — não dá para entrar sem confirmar —, então o
            # dono legítimo do e-mail que se cadastra depois não pode herdar a
            # senha de quem digitou o endereço antes dele. Quem clicar no link
            # mais novo precisa ficar com as credenciais que ele mesmo digitou:
            # o pendente some e o cadastro segue como se fosse novo.
            agencia_antiga = existente.agency
            sozinho = agencia_antiga is not None and all(
                u.id == existente.id for u in agencia_antiga.users
            )
            logger.info("Cadastro descartou cadastro não verificado %s", existente.id)
            db.session.delete(agencia_antiga if sozinho else existente)
            db.session.flush()
        elif pendente:
            # Convidado sem senha: não há credencial alheia a proteger, só reenvia.
            _enviar_verificacao(existente)
            return
        else:
            enviar(emails.conta_existente(dados.email))
            return
    if db.session.scalar(select(Agency.id).where(Agency.cnpj == dados.cnpj)) is not None:
        enviar(emails.cnpj_em_uso(dados.email, dados.cnpj))
        return

    agencia = Agency(name=dados.agency_name, cnpj=dados.cnpj, plan=None)
    user = User(
        email=dados.email, name=dados.name, password_hash=gerar_hash(dados.password),
        role=UserRole.ADMIN, agency=agencia, termos_aceitos_em=datetime.now(timezone.utc),
    )
    db.session.add_all([agencia, user])
    try:
        db.session.commit()
    except IntegrityError:
        # Dois cadastros simultâneos com o mesmo e-mail ou CNPJ: o segundo perde
        # a corrida, e quem chegou primeiro já recebeu o link.
        db.session.rollback()
        enviar(emails.conta_existente(dados.email))
        return
    logger.info("Cadastro: usuário %s + agência %s", user.id, agencia.id)
    _enviar_verificacao(user)


def _conferir_senha_do_cadastro(user: User, senha: str | None) -> None:
    if senha is None:
        raise BadRequestError(
            "Digite a senha que você escolheu no cadastro.", code="verification_password_required"
        )
    ip = ip_do_cliente()
    conferir_limite(_POR_IP, ip)
    conferir_limite(_POR_EMAIL, user.email)
    if not conferir(senha, user.password_hash):
        registrar_tentativa(_POR_IP, ip)
        registrar_tentativa(_POR_EMAIL, user.email)
        raise BadRequestError(
            "A senha não confere com a do cadastro deste link.", code="verification_password_invalid"
        )
    zerar(_POR_EMAIL, user.email)


def verificar_email(token: str, senha: str | None = None) -> User:
    # Lê antes de consumir: senha ausente ou errada não pode gastar o link.
    user = token_service.ler(token, FinalidadeToken.VERIFICAR_EMAIL)
    if user.password_hash:
        _conferir_senha_do_cadastro(user, senha)
    user = token_service.consumir(token, FinalidadeToken.VERIFICAR_EMAIL)
    if user.email_verificado_em is None:
        user.email_verificado_em = datetime.now(timezone.utc)
    db.session.commit()
    return user


def reenviar_verificacao(email: str) -> None:
    em_segundo_plano(_processar_reenvio, email)


def _processar_reenvio(email: str) -> None:
    user = user_service.find_by_email(email)
    if user is not None and user.deleted_at is None and user.email_verificado_em is None:
        _enviar_verificacao(user)
