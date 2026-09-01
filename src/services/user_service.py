"""Gestão de membros da agência."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Select, func, select

from src.extensions import db
from src.models import OAuthProvider, User, UserRole
from src.utils.errors import ConflictError


def build_user_query(agency_id: uuid.UUID) -> Select:
    """SELECT dos membros ativos da agência, em ordem alfabética."""
    return (
        select(User)
        .where(User.agency_id == agency_id, User.deleted_at.is_(None))
        .order_by(User.name.asc())
    )


def find_by_email(email: str) -> User | None:
    return db.session.scalar(select(User).where(User.email == email))


def find_first_by_role(role: UserRole) -> User | None:
    return db.session.scalar(select(User).where(User.role == role))


def create_member(
    *,
    email: str,
    name: str,
    role: UserRole,
    oauth_provider: OAuthProvider,
    agency_id: uuid.UUID,
) -> User:
    """Cria o membro. E-mail é único na base inteira, não só na agência."""
    if find_by_email(email) is not None:
        raise ConflictError("Email já cadastrado", details={"email": email})

    user = User(
        email=email,
        name=name,
        oauth_provider=oauth_provider,
        # oauth_id provisório até o membro logar de fato via OAuth.
        oauth_id=f"pending-{email}",
        role=role,
        agency_id=agency_id,
    )
    db.session.add(user)
    db.session.commit()
    return user


def apply_update(user: User, data: dict) -> User:
    for field, value in data.items():
        setattr(user, field, value)
    db.session.commit()
    return user


def soft_delete(user: User) -> None:
    user.deleted_at = datetime.now(timezone.utc)
    db.session.commit()


def _restam_administradores(user: User) -> bool:
    """Há outro admin ativo na agência além deste usuário?

    Conta só quem pode de fato administrar: usuário logicamente apagado ainda
    ocupa linha na tabela, e tratá-lo como admin deixaria a agência sem
    ninguém que possa convidar membros ou encerrar a conta.
    """
    if user.agency_id is None:
        return False
    outro = db.session.scalar(
        select(User.id).where(
            User.agency_id == user.agency_id,
            User.id != user.id,
            User.role == UserRole.ADMIN,
            User.deleted_at.is_(None),
        )
    )
    return outro is not None


def preview_own_deletion(user: User) -> dict:
    """Contagem do que a exclusão levaria, para a interface avisar antes.

    Números, e não só "isto apaga tudo": o titular precisa reconhecer o que
    vai perder para decidir, e um aviso genérico não dá como reconhecer.
    """
    from src.models import Campaign, Influencer, Report

    leva_a_agencia = user.agency_id is not None and not _restam_administradores(user)
    if not leva_a_agencia:
        return {"scope": "account", "agency": None}

    def quantos(modelo):
        return db.session.scalar(
            select(func.count()).select_from(modelo).where(modelo.agency_id == user.agency_id)
        ) or 0

    return {
        "scope": "agency",
        "agency": {
            "name": user.agency.name if user.agency else None,
            "influencers": quantos(Influencer),
            "campaigns": quantos(Campaign),
            "reports": quantos(Report),
            "members": db.session.scalar(
                select(func.count()).select_from(User).where(
                    User.agency_id == user.agency_id, User.deleted_at.is_(None)
                )
            ) or 0,
        },
    }


def erase_own_account(user: User) -> dict:
    """Exclusão definitiva pedida pelo próprio titular. Não há soft delete aqui.

    Duas consequências diferentes, e o retorno diz qual aconteceu, porque a
    interface precisa avisar antes e confirmar depois:

    - **Sobra administrador** na agência: apaga só este usuário. A agência
      segue viva, e os relatórios que ele gerou ficam (o FK é `SET NULL`) —
      apagar relatório de campanha por causa da saída de um membro seria
      destruir dado de terceiro.
    - **Não sobra**: a agência ficaria sem quem a administre, então ela vai
      junto e o cascade leva criadores, contas conectadas, publicações,
      comentários, campanhas, relatórios e o log de uso de API.

    O soft delete continua existindo para remoção de membro **por um admin**
    (`soft_delete`), que é outra operação: lá o titular não pediu nada.
    """
    agencia = user.agency
    leva_a_agencia = agencia is not None and not _restam_administradores(user)

    resultado = {
        "deleted": "agency" if leva_a_agencia else "account",
        "agency_id": str(agencia.id) if leva_a_agencia else None,
    }
    # A agência cascateia para os usuários; apagar os dois seria apagar o
    # mesmo registro duas vezes.
    db.session.delete(agencia if leva_a_agencia else user)
    db.session.commit()
    return resultado
