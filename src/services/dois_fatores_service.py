"""2FA por app autenticador (TOTP) — spec de 19/10/2026.

O que este módulo garante, e de onde vem cada garantia:

- **Cada código vale uma vez** (NIST SP 800-63B-4, §3.1.5.2). O passo de tempo
  aceito é gravado com UPDATE condicional (`totp_ultimo_passo < passo`): dois
  pedidos simultâneos com o mesmo código não passam os dois, e um código de um
  passo anterior ao último aceito é recusado mesmo dentro da janela.
- **Limite de tentativas** (§3.1.5.2): 5 falhas a cada 15 minutos por conta.
  Passado o limite, até o código certo é barrado até a janela vencer.
- **Segredo protegido** (§3.1.5.2): cifrado com a FERNET_KEY.
- **Códigos de recuperação de uso único** (OWASP, "Resetting MFA"): guardados
  como HMAC com chave fora do banco; o uso é marcado com UPDATE condicional.
- **Trocar ou desligar exige um fator já cadastrado** e gera aviso por e-mail
  (OWASP, "Changing MFA Factors").

Erro de código é 422 no campo, e não 401: o front lê 401 como sessão vencida.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timezone

import segno
from flask import current_app
from sqlalchemy import delete, or_, update

from src.extensions import db
from src.integrations.email import enviar
from src.models import CodigoRecuperacao, User, UserRole
from src.services import emails
from src.services.auth_service import invalidar_sessoes
from src.utils import totp
from src.utils.crypto import decrypt_token, encrypt_token
from src.utils.errors import ConflictError, ForbiddenError
from src.utils.rate_limit import conferir_limite, registrar_tentativa, zerar
from src.utils.senha import conferir
from src.utils.validation import erro_de_campo

logger = logging.getLogger(__name__)

_LIMITE = "RATE_LIMIT_2FA"
QUANTIDADE_DE_CODIGOS = 10
# Sem i, l, o, 0 e 1: o código é lido de um papel e digitado à mão.
_ALFABETO = "abcdefghjkmnpqrstuvwxyz23456789"
_TAMANHO_DO_CODIGO = 8
CODIGO_INVALIDO = "código inválido ou já usado"


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _avisar(user: User, evento: str) -> None:
    enviar(emails.aviso_2fa(user, evento))


# ---------------------------------------------------------------- recuperação
def _chave_dos_codigos() -> bytes:
    # Derivada, e não a FERNET_KEY crua: a mesma chave não serve a dois usos.
    segredo = current_app.config["FERNET_KEY"].encode("utf-8")
    return hashlib.sha256(b"lumina:codigos-de-recuperacao:" + segredo).digest()


def _normalizar(digitado: str) -> str:
    return "".join(c for c in digitado.lower() if c not in " -")


def _hash_do_codigo(digitado: str) -> str:
    return hmac.new(_chave_dos_codigos(), _normalizar(digitado).encode("utf-8"),
                    hashlib.sha256).hexdigest()


def _gerar_codigos(user: User) -> list[str]:
    """Troca todos os códigos de recuperação da conta por 10 novos. Sem commit."""
    db.session.execute(delete(CodigoRecuperacao).where(CodigoRecuperacao.user_id == user.id))
    codigos = []
    for _ in range(QUANTIDADE_DE_CODIGOS):
        cru = "".join(secrets.choice(_ALFABETO) for _ in range(_TAMANHO_DO_CODIGO))
        codigos.append(f"{cru[:4]}-{cru[4:]}")
        db.session.add(CodigoRecuperacao(user_id=user.id, codigo_hash=_hash_do_codigo(cru)))
    db.session.expire(user, ["codigos_recuperacao"])
    return codigos


def _usar_codigo_de_recuperacao(user: User, digitado: str) -> bool:
    normalizado = _normalizar(digitado)
    if len(normalizado) != _TAMANHO_DO_CODIGO:
        return False
    resultado = db.session.execute(
        update(CodigoRecuperacao)
        .where(
            CodigoRecuperacao.user_id == user.id,
            CodigoRecuperacao.codigo_hash == _hash_do_codigo(normalizado),
            CodigoRecuperacao.usado_em.is_(None),
        )
        .values(usado_em=_agora())
        .execution_options(synchronize_session=False)
    )
    if resultado.rowcount == 1:
        db.session.expire(user, ["codigos_recuperacao"])
        return True
    return False


# ---------------------------------------------------------------- TOTP
def _segredo(user: User) -> str | None:
    return decrypt_token(user.totp_segredo_cifrado)


def _aceitar_codigo_do_app(user: User, digitado: str) -> bool:
    segredo = _segredo(user)
    passo = totp.passo_do_codigo(segredo, digitado.strip()) if segredo else None
    if passo is None:
        return False
    resultado = db.session.execute(
        update(User)
        .where(
            User.id == user.id,
            or_(User.totp_ultimo_passo.is_(None), User.totp_ultimo_passo < passo),
        )
        .values(totp_ultimo_passo=passo)
        .execution_options(synchronize_session=False)
    )
    if resultado.rowcount == 1:
        db.session.expire(user, ["totp_ultimo_passo"])
        return True
    return False


def _conferir(user: User, digitado: str, *, campo: str, aceita_recuperacao: bool) -> str:
    """Confere o código sob o limite de tentativas. Devolve "app" ou "recuperacao"."""
    chave = str(user.id)
    conferir_limite(_LIMITE, chave)
    if _aceitar_codigo_do_app(user, digitado):
        tipo = "app"
    elif aceita_recuperacao and _usar_codigo_de_recuperacao(user, digitado):
        tipo = "recuperacao"
    else:
        registrar_tentativa(_LIMITE, chave)
        raise erro_de_campo(campo, CODIGO_INVALIDO, "invalid_mfa_code")
    zerar(_LIMITE, chave)
    return tipo


def verificar_codigo(user: User, digitado: str, *, campo: str = "code") -> str:
    """Segundo fator de quem já tem 2FA: código do app ou de recuperação. Faz commit."""
    tipo = _conferir(user, digitado, campo=campo, aceita_recuperacao=True)
    db.session.commit()
    if tipo == "recuperacao":
        logger.info("Código de recuperação usado pelo usuário %s", user.id)
        _avisar(user, "codigo_usado")
    return tipo


# ---------------------------------------------------------------- ciclo de vida
def iniciar_ativacao(user: User) -> dict:
    """Gera um segredo pendente. Chamar de novo troca o pendente por outro."""
    if user.mfa_enabled:
        raise ConflictError("O 2FA já está ativo nesta conta.", code="mfa_already_enabled")
    segredo = totp.gerar_segredo()
    user.totp_segredo_cifrado = encrypt_token(segredo)
    user.totp_ultimo_passo = None
    db.session.commit()
    uri = totp.uri_de_provisionamento(segredo, user.email)
    return {
        "secret": segredo,
        "otpauth_uri": uri,
        "qr_svg": segno.make(uri, error="m").svg_data_uri(scale=5, border=2),
    }


def confirmar_ativacao(user: User, digitado: str) -> list[str]:
    """Liga o 2FA com o primeiro código do app. Devolve os códigos de recuperação.

    Encerra as outras sessões: uma sessão aberta com uma senha roubada não
    sobrevive à ativação. O commit fica com quem chama, junto com o ticket.
    """
    if user.mfa_enabled:
        raise ConflictError("O 2FA já está ativo nesta conta.", code="mfa_already_enabled")
    if not user.totp_segredo_cifrado:
        raise ConflictError("Comece a ativação antes de confirmar.", code="mfa_setup_not_started")
    _conferir(user, digitado, campo="code", aceita_recuperacao=False)
    user.totp_ativado_em = _agora()
    codigos = _gerar_codigos(user)
    invalidar_sessoes(user)
    logger.info("2FA ativado pelo usuário %s", user.id)
    _avisar(user, "ativado")
    return codigos


def novos_codigos(user: User, digitado: str) -> list[str]:
    """Troca os códigos de recuperação. Exige um código válido; faz commit."""
    if not user.mfa_enabled:
        raise ConflictError("O 2FA não está ativo nesta conta.", code="mfa_not_enabled")
    _conferir(user, digitado, campo="code", aceita_recuperacao=True)
    codigos = _gerar_codigos(user)
    db.session.commit()
    logger.info("Novos códigos de recuperação para o usuário %s", user.id)
    _avisar(user, "novos_codigos")
    return codigos


def _limpar(user: User) -> None:
    user.totp_segredo_cifrado = None
    user.totp_ativado_em = None
    user.totp_ultimo_passo = None
    db.session.execute(delete(CodigoRecuperacao).where(CodigoRecuperacao.user_id == user.id))
    db.session.expire(user, ["codigos_recuperacao"])


def desativar(user: User, digitado: str, senha: str | None) -> None:
    """Desliga o 2FA de membro ou visualizador. Administrador não pode."""
    if user.role == UserRole.ADMIN and current_app.config.get("MFA_OBRIGATORIO_PARA_ADMIN", True):
        raise ForbiddenError("O 2FA é obrigatório para administradores.",
                             code="mfa_required_for_admin")
    if not user.mfa_enabled:
        raise ConflictError("O 2FA não está ativo nesta conta.", code="mfa_not_enabled")
    if user.password_hash:
        if not senha:
            raise erro_de_campo("password", "informe sua senha", "missing")
        if not conferir(senha, user.password_hash):
            raise erro_de_campo("password", "senha incorreta", "invalid_password")
    _conferir(user, digitado, campo="code", aceita_recuperacao=True)
    _limpar(user)
    db.session.commit()
    logger.info("2FA desligado pelo usuário %s", user.id)
    _avisar(user, "desativado")


def resetar_por_comando(email: str) -> None:
    """Usado pelo `flask users reset-2fa`. Levanta ValueError com a frase do erro."""
    from src.services import user_service

    user = user_service.find_by_email(email)
    if user is None or user.deleted_at is not None:
        raise ValueError("usuário não encontrado")
    _limpar(user)
    invalidar_sessoes(user)
    db.session.commit()
    logger.info("2FA zerado por comando para o usuário %s", user.id)
    _avisar(user, "resetado")
