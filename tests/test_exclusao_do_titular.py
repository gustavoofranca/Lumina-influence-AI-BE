"""Exclusão pedida pelo próprio titular — conta, agência e histórico coletado.

Existe separado de `test_crud.py` porque não é CRUD: é o direito de eliminação
da LGPD (art. 18, VI) exercido pelo dono do dado, e o que se mede aqui é
**consequência**, não código de resposta. As duas operações abaixo são
irreversíveis e não têm soft delete; o que as diferencia da remoção de membro
feita por um admin é justamente quem pediu.

Cada teste monta a sua própria agência descartável. Reaproveitar a do `ctx`
apagaria o cenário no meio da suíte.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest

from src.extensions import db
from src.models import (
    Agency,
    Campaign,
    CampaignStatus,
    Comment,
    Influencer,
    InfluencerStatus,
    Platform,
    Post,
    PostType,
    SocialAccount,
    User,
    UserRole,
)
from src.models._enums import OAuthProvider
from src.utils.crypto import encrypt_token
from src.utils.jwt_utils import issue_token_pair


class Cenario:
    pass


def _usuario(agencia, email, role):
    u = User(
        email=email, name=email.split("@")[0], oauth_provider=OAuthProvider.GOOGLE,
        oauth_id=f"oauth-{email}-{uuid.uuid4()}", role=role, agency=agencia,
    )
    db.session.add(u)
    return u


@pytest.fixture()
def cenario(app):
    """Agência descartável com um criador conectado, posts, comentário e campanha."""
    with app.app_context():
        agencia = Agency(name=f"Descartável {uuid.uuid4().hex[:6]}")
        db.session.add(agencia)
        db.session.flush()

        admin = _usuario(agencia, f"admin-{uuid.uuid4().hex[:6]}@desc.com", UserRole.ADMIN)
        membro = _usuario(agencia, f"membro-{uuid.uuid4().hex[:6]}@desc.com", UserRole.MEMBER)

        criador = Influencer(agency=agencia, display_name="Criador Desc", niche="tech",
                             status=InfluencerStatus.ACTIVE)
        db.session.add(criador)
        db.session.flush()

        conta = SocialAccount(
            influencer=criador, platform=Platform.INSTAGRAM, handle="desc",
            follower_count=100, access_token_encrypted=encrypt_token("tok"),
            last_synced_at=datetime.now(timezone.utc),
        )
        db.session.add(conta)
        db.session.flush()

        for i in range(3):
            post = Post(
                social_account_id=conta.id, platform_post_id=f"p-{i}", post_type=PostType.IMAGE,
                posted_at=datetime.now(timezone.utc), reach_total=10, reach_organic=10,
                reach_paid=0, impressions=12, likes=1, comments_count=1, shares=0, saves=0,
            )
            db.session.add(post)
            db.session.flush()
            db.session.add(Comment(
                post_id=post.id, platform_comment_id=f"c-{i}", content="oi",
                posted_at=datetime.now(timezone.utc),
            ))

        db.session.add(Campaign(
            agency=agencia, brand_name="Marca Desc", period_start=date(2026, 1, 1),
            period_end=date(2026, 2, 1), status=CampaignStatus.ACTIVE,
        ))
        db.session.commit()

        c = Cenario()
        c.agencia_id = agencia.id
        c.criador_id = criador.id
        c.conta_id = conta.id
        c.admin_id = admin.id
        c.membro_id = membro.id
        c.h_admin = {"Authorization": f"Bearer {issue_token_pair(admin)['access_token']}"}
        c.h_membro = {"Authorization": f"Bearer {issue_token_pair(membro)['access_token']}"}
        yield c

        # A agência pode já ter sido apagada pelo próprio teste.
        sobrou = db.session.get(Agency, c.agencia_id)
        if sobrou is not None:
            db.session.delete(sobrou)
            db.session.commit()


@pytest.fixture()
def intruso(app):
    """Admin de outra agência, para as sondas de escopo."""
    with app.app_context():
        outra = Agency(name=f"Intrusa {uuid.uuid4().hex[:6]}")
        db.session.add(outra)
        db.session.flush()
        admin = _usuario(outra, f"intruso-{uuid.uuid4().hex[:6]}@outra.com", UserRole.ADMIN)
        db.session.commit()
        yield {"Authorization": f"Bearer {issue_token_pair(admin)['access_token']}"}
        db.session.delete(db.session.get(Agency, outra.id))
        db.session.commit()


def _conta_posts(conta_id):
    from sqlalchemy import func, select
    return db.session.scalar(
        select(func.count()).select_from(Post).where(Post.social_account_id == conta_id)
    )


# ==========================================================================
# Desconectar apagando o histórico coletado
# ==========================================================================
def test_desconectar_sem_purgar_continua_preservando_o_historico(client, cenario):
    # O padrão não mudou: é o comportamento que a política publicada descreve.
    r = client.post(
        f"/api/v1/integrations/instagram/disconnect/{cenario.conta_id}",
        headers=cenario.h_admin, json={},
    )
    assert r.status_code == 200
    assert r.get_json()["data"]["posts_deleted"] == 0
    db.session.expire_all()
    assert _conta_posts(cenario.conta_id) == 3


def test_desconectar_purgando_apaga_publicacoes_e_comentarios(client, cenario):
    from sqlalchemy import func, select

    r = client.post(
        f"/api/v1/integrations/instagram/disconnect/{cenario.conta_id}",
        headers=cenario.h_admin, json={"purge_collected": True},
    )
    assert r.status_code == 200
    corpo = r.get_json()["data"]
    assert corpo["purged"] is True
    assert corpo["posts_deleted"] == 3

    db.session.expire_all()
    assert _conta_posts(cenario.conta_id) == 0
    # Comentário sem post é dado pessoal órfão: o cascade precisa levá-lo.
    assert db.session.scalar(select(func.count()).select_from(Comment)) == 0

    # A conta sobrevive sem token: ela registra o vínculo, não o dado coletado.
    conta = db.session.get(SocialAccount, cenario.conta_id)
    assert conta is not None
    assert conta.access_token_encrypted is None
    assert conta.last_synced_at is None


def test_purgar_conta_de_outra_agencia_nao_apaga_nada(client, cenario, intruso):
    # A operação é destrutiva e escopada: quem não é da agência não pode nem
    # descobrir que a conta existe, muito menos apagar o histórico dela.
    r = client.post(
        f"/api/v1/integrations/instagram/disconnect/{cenario.conta_id}",
        headers=intruso, json={"purge_collected": True},
    )
    assert r.status_code == 404
    db.session.expire_all()
    assert _conta_posts(cenario.conta_id) == 3


# ==========================================================================
# Prévia: o titular precisa saber o que perde antes de confirmar
# ==========================================================================
def test_previa_do_membro_diz_que_so_a_conta_dele_vai(client, cenario):
    r = client.get("/api/v1/users/me/deletion-preview", headers=cenario.h_membro)
    assert r.status_code == 200
    assert r.get_json()["data"]["scope"] == "account"


def test_previa_do_unico_admin_conta_o_que_vai_junto(client, cenario):
    r = client.get("/api/v1/users/me/deletion-preview", headers=cenario.h_admin)
    assert r.status_code == 200
    dados = r.get_json()["data"]
    assert dados["scope"] == "agency"
    # Números, e não só "isto apaga tudo": o titular precisa reconhecer o que
    # vai perder para poder decidir.
    assert dados["agency"]["influencers"] == 1
    assert dados["agency"]["campaigns"] == 1
    assert dados["agency"]["members"] == 2


def test_previa_muda_quando_existe_outro_admin(client, cenario):
    outro = db.session.get(User, cenario.membro_id)
    outro.role = UserRole.ADMIN
    db.session.commit()

    r = client.get("/api/v1/users/me/deletion-preview", headers=cenario.h_admin)
    assert r.get_json()["data"]["scope"] == "account"


# ==========================================================================
# Exclusão da própria conta
# ==========================================================================
def test_membro_que_se_exclui_nao_leva_a_agencia(client, cenario):
    r = client.delete("/api/v1/users/me", headers=cenario.h_membro)
    assert r.status_code == 200
    assert r.get_json()["data"]["deleted"] == "account"

    db.session.expire_all()
    assert db.session.get(User, cenario.membro_id) is None
    # Apagado de verdade, não marcado: o titular pediu eliminação.
    assert db.session.get(Agency, cenario.agencia_id) is not None
    assert db.session.get(Influencer, cenario.criador_id) is not None


def test_unico_admin_que_se_exclui_leva_a_agencia_e_o_que_foi_coletado(client, cenario):
    from sqlalchemy import func, select

    r = client.delete("/api/v1/users/me", headers=cenario.h_admin)
    assert r.status_code == 200
    assert r.get_json()["data"]["deleted"] == "agency"

    db.session.expire_all()
    assert db.session.get(Agency, cenario.agencia_id) is None
    assert db.session.get(User, cenario.admin_id) is None
    assert db.session.get(User, cenario.membro_id) is None
    assert db.session.get(Influencer, cenario.criador_id) is None
    assert db.session.get(SocialAccount, cenario.conta_id) is None
    # O cascade precisa chegar até a ponta: post e comentário são o dado
    # pessoal de terceiros que a agência coletou.
    assert db.session.scalar(select(func.count()).select_from(Post)) == 0
    assert db.session.scalar(select(func.count()).select_from(Comment)) == 0


def test_admin_com_companhia_leva_so_a_propria_conta(client, cenario):
    outro = db.session.get(User, cenario.membro_id)
    outro.role = UserRole.ADMIN
    db.session.commit()

    r = client.delete("/api/v1/users/me", headers=cenario.h_admin)
    assert r.get_json()["data"]["deleted"] == "account"

    db.session.expire_all()
    assert db.session.get(Agency, cenario.agencia_id) is not None
    assert db.session.get(User, cenario.membro_id) is not None


def test_admin_soft_deletado_nao_conta_como_administrador_restante(client, cenario):
    # Usuário logicamente apagado ainda ocupa linha na tabela. Tratá-lo como
    # admin deixaria a agência sem ninguém que possa administrá-la.
    outro = db.session.get(User, cenario.membro_id)
    outro.role = UserRole.ADMIN
    outro.deleted_at = datetime.now(timezone.utc)
    db.session.commit()

    r = client.delete("/api/v1/users/me", headers=cenario.h_admin)
    assert r.get_json()["data"]["deleted"] == "agency"


def test_excluir_a_propria_conta_exige_autenticacao(client, cenario):
    assert client.delete("/api/v1/users/me").status_code == 401
    assert client.get("/api/v1/users/me/deletion-preview").status_code == 401


def test_a_rota_de_membro_continua_sendo_soft_delete_e_de_outra_pessoa(client, cenario):
    # As duas rotas coexistem e não são a mesma coisa: `DELETE /users/{id}` é
    # remoção de membro por um admin, é lógica, e proíbe auto-remoção. Se um dia
    # alguém as unificar, este teste cai — e deve cair.
    r = client.delete(f"/api/v1/users/{cenario.membro_id}", headers=cenario.h_admin)
    assert r.status_code == 204

    db.session.expire_all()
    ainda = db.session.get(User, cenario.membro_id)
    assert ainda is not None
    assert ainda.deleted_at is not None


def test_admin_nao_consegue_se_remover_pela_rota_de_membro(client, cenario):
    r = client.delete(f"/api/v1/users/{cenario.admin_id}", headers=cenario.h_admin)
    assert r.status_code == 422
    assert r.get_json()["error"]["code"] == "cannot_delete_self"
