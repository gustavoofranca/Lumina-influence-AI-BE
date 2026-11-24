"""Escopo por agência pedido ao domínio de Criadores (ARQ-01, fase F1).

`contas_da_agencia` é a única porta pela qual outro domínio descobre quais
contas sociais são de uma agência (ADR-008). Se ela deixar vazar conta alheia,
todo serviço que filtra por ela vaza junto — por isso o teste cobre os dois
lados da fronteira, e não só o caso feliz.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from src.extensions import db
from src.models import Agency, Influencer, Platform, Post, PostType, SocialAccount
from src.services import post_service, social_account_service
from src.utils.errors import NotFoundError


class _Ctx:
    pass


@pytest.fixture()
def ctx(app):
    with app.app_context():
        agencia_a = Agency(name="Agência Escopo A")
        agencia_b = Agency(name="Agência Escopo B")
        agencia_vazia = Agency(name="Agência Escopo Vazia")
        db.session.add_all([agencia_a, agencia_b, agencia_vazia])
        db.session.flush()

        inf_a = Influencer(agency=agencia_a, display_name="Criador A")
        inf_b = Influencer(agency=agencia_b, display_name="Criador B")
        # Criador sem conta: não pode fazer a agência dele aparecer com conta.
        inf_sem_conta = Influencer(agency=agencia_vazia, display_name="Criador Sem Conta")
        db.session.add_all([inf_a, inf_b, inf_sem_conta])
        db.session.flush()

        conta_a1 = SocialAccount(influencer=inf_a, platform=Platform.INSTAGRAM, handle="esc_a1")
        conta_a2 = SocialAccount(influencer=inf_a, platform=Platform.TIKTOK, handle="esc_a2")
        conta_b = SocialAccount(influencer=inf_b, platform=Platform.INSTAGRAM, handle="esc_b")
        db.session.add_all([conta_a1, conta_a2, conta_b])
        db.session.flush()

        agora = datetime.now(timezone.utc)
        post_a = Post(
            social_account=conta_a1, platform_post_id="esc-post-a",
            post_type=PostType.IMAGE, posted_at=agora,
        )
        post_b = Post(
            social_account=conta_b, platform_post_id="esc-post-b",
            post_type=PostType.IMAGE, posted_at=agora,
        )
        db.session.add_all([post_a, post_b])
        db.session.commit()

        c = _Ctx()
        c.agencias = [agencia_a.id, agencia_b.id, agencia_vazia.id]
        c.agencia_a, c.agencia_b, c.agencia_vazia = c.agencias
        c.contas_a = {conta_a1.id, conta_a2.id}
        c.conta_b = conta_b.id
        c.post_a, c.post_b = post_a.id, post_b.id
    yield c
    with app.app_context():
        for agency_id in c.agencias:
            restante = db.session.get(Agency, agency_id)
            if restante is not None:
                db.session.delete(restante)
        db.session.commit()


def _ids(agency_id) -> set[uuid.UUID]:
    return set(db.session.scalars(social_account_service.contas_da_agencia(agency_id)))


def test_contas_da_agencia_traz_as_contas_da_agencia(app, ctx):
    with app.app_context():
        assert _ids(ctx.agencia_a) == ctx.contas_a


def test_contas_da_agencia_nao_traz_conta_de_outra_agencia(app, ctx):
    with app.app_context():
        assert ctx.conta_b not in _ids(ctx.agencia_a)
        assert _ids(ctx.agencia_b) == {ctx.conta_b}


def test_contas_da_agencia_sem_conta_devolve_vazio(app, ctx):
    with app.app_context():
        assert _ids(ctx.agencia_vazia) == set()
        assert _ids(uuid.uuid4()) == set()


def test_post_da_agencia_vem_com_conta_e_criador(app, ctx):
    with app.app_context():
        post = post_service.load_scoped_post(str(ctx.post_a), ctx.agencia_a)
        assert post.id == ctx.post_a
        # A análise de IA lê o nicho por aqui; o escopo não pode cortar o caminho.
        assert post.social_account.influencer.display_name == "Criador A"


def test_post_de_outra_agencia_e_404(app, ctx):
    with app.app_context():
        with pytest.raises(NotFoundError):
            post_service.load_scoped_post(str(ctx.post_b), ctx.agencia_a)
        with pytest.raises(NotFoundError):
            post_service.load_scoped_post(str(ctx.post_a), ctx.agencia_vazia)
