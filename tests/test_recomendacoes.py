"""Decisões da agência sobre as recomendações da IA.

O que se mede aqui é persistência com autoria: antes desta frente, aceitar uma
recomendação acontecia só na tela — sumia ao recarregar e ninguém respondia por
ela. Numa ferramenta de auditoria isso é defeito de produto, não de interface.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from src.extensions import db
from src.models import (
    Agency,
    AIAnalysis,
    Influencer,
    InfluencerStatus,
    Platform,
    Post,
    PostType,
    RecommendationDecision,
    SentimentLabel,
    SocialAccount,
    User,
    UserRole,
)
from src.models._enums import OAuthProvider
from src.utils.jwt_utils import issue_token_pair

RECS = [
    {"priority": "high", "title": "Publicar mais reels", "description": "..."},
    {"priority": "medium", "title": "Responder comentários", "description": "..."},
]


class Cena:
    pass


@pytest.fixture()
def cena(app):
    with app.app_context():
        agencia = Agency(name=f"Rec {uuid.uuid4().hex[:6]}")
        db.session.add(agencia)
        db.session.flush()
        admin = User(email=f"a-{uuid.uuid4().hex[:6]}@rec.com", name="Marina",
                     oauth_provider=OAuthProvider.GOOGLE, oauth_id=str(uuid.uuid4()),
                     role=UserRole.ADMIN, agency=agencia)
        db.session.add(admin)

        criador = Influencer(agency=agencia, display_name="Criador Rec", niche="tech",
                             status=InfluencerStatus.ACTIVE)
        db.session.add(criador)
        db.session.flush()
        conta = SocialAccount(influencer=criador, platform=Platform.INSTAGRAM,
                              handle="rec", follower_count=10)
        db.session.add(conta)
        db.session.flush()
        post = Post(social_account_id=conta.id, platform_post_id="p-rec",
                    post_type=PostType.IMAGE, posted_at=datetime.now(timezone.utc),
                    reach_total=1, reach_organic=1, reach_paid=0, impressions=1,
                    likes=0, comments_count=0, shares=0, saves=0)
        db.session.add(post)
        db.session.flush()
        analise = AIAnalysis(post_id=post.id, model_version="teste",
                             sentiment_score=0.5, sentiment_label=SentimentLabel.POSITIVE,
                             recommendations=RECS)
        db.session.add(analise)
        db.session.commit()

        c = Cena()
        c.agencia_id = agencia.id
        c.criador_id = criador.id
        c.analise_id = analise.id
        c.admin_nome = admin.name
        c.h = {"Authorization": f"Bearer {issue_token_pair(admin)['access_token']}"}
        yield c

        db.session.delete(db.session.get(Agency, c.agencia_id))
        db.session.commit()


def _decidir(client, cena, indice, decisao):
    return client.put(
        f"/api/v1/influencers/{cena.criador_id}/recommendations/{indice}",
        headers=cena.h, json={"analysis_id": str(cena.analise_id), "decision": decisao},
    )


def _analise(client, cena):
    r = client.get(f"/api/v1/influencers/{cena.criador_id}/analysis", headers=cena.h)
    return r.get_json()["data"]


# ==========================================================================
# A decisão sobrevive ao recarregar — que era o defeito
# ==========================================================================
def test_a_decisao_volta_junto_com_a_recomendacao(client, cena):
    assert _decidir(client, cena, 0, "accepted").status_code == 200

    recs = _analise(client, cena)["recommendations"]
    # Sem isto a tela recarregada volta a oferecer "aceitar" para algo que a
    # agência já aceitou.
    assert recs[0]["decision"] == "accepted"
    assert recs[1]["decision"] is None


def test_a_decisao_registra_quem_a_tomou(client, cena):
    _decidir(client, cena, 0, "accepted")
    rec = _analise(client, cena)["recommendations"][0]
    # Auditoria em que ninguém responde pelo aceite não é auditoria.
    assert rec["decided_by"] == cena.admin_nome
    assert rec["decided_at"] is not None


def test_o_indice_vem_no_payload_como_identidade_do_item(client, cena):
    recs = _analise(client, cena)["recommendations"]
    assert [r["index"] for r in recs] == [0, 1]


# ==========================================================================
# Trocar, desfazer, e não duplicar
# ==========================================================================
def test_decidir_de_novo_troca_em_vez_de_empilhar(client, cena):
    _decidir(client, cena, 0, "accepted")
    _decidir(client, cena, 0, "ignored")

    db.session.expire_all()
    total = db.session.scalar(
        select(func.count()).select_from(RecommendationDecision)
        .where(RecommendationDecision.analysis_id == cena.analise_id)
    )
    assert total == 1
    assert _analise(client, cena)["recommendations"][0]["decision"] == "ignored"


def test_desfazer_devolve_a_recomendacao_ao_estado_indeciso(client, cena):
    _decidir(client, cena, 0, "accepted")
    r = client.delete(
        f"/api/v1/influencers/{cena.criador_id}/recommendations/0"
        f"?analysis_id={cena.analise_id}", headers=cena.h,
    )
    assert r.status_code == 204
    assert _analise(client, cena)["recommendations"][0]["decision"] is None


def test_desfazer_o_que_nao_foi_decidido_e_404(client, cena):
    r = client.delete(
        f"/api/v1/influencers/{cena.criador_id}/recommendations/1"
        f"?analysis_id={cena.analise_id}", headers=cena.h,
    )
    assert r.status_code == 404


# ==========================================================================
# O índice vem do cliente: as duas guardas
# ==========================================================================
def test_indice_fora_da_lista_e_recusado(client, cena):
    # Decisão apontando para nada reaparece como órfã quando a análise muda.
    r = _decidir(client, cena, 99, "accepted")
    assert r.status_code == 422
    assert r.get_json()["error"]["details"]["total"] == 2


def test_analise_de_outro_criador_nao_grava_decisao_aqui(client, cena, app):
    # Sem esta checagem, o id de uma análise alheia gravaria decisão neste
    # criador — e a decisão apareceria na tela de quem não a tomou.
    with app.app_context():
        outra = Influencer(agency_id=cena.agencia_id, display_name="Outro",
                           niche="food", status=InfluencerStatus.ACTIVE)
        db.session.add(outra)
        db.session.commit()
        r = client.put(
            f"/api/v1/influencers/{outra.id}/recommendations/0",
            headers=cena.h,
            json={"analysis_id": str(cena.analise_id), "decision": "accepted"},
        )
        assert r.status_code == 404


def test_decisao_invalida_e_recusada(client, cena):
    r = _decidir(client, cena, 0, "talvez")
    assert r.status_code == 422


def test_sem_analysis_id_e_erro_de_validacao(client, cena):
    r = client.put(
        f"/api/v1/influencers/{cena.criador_id}/recommendations/0",
        headers=cena.h, json={"decision": "accepted"},
    )
    assert r.status_code == 422


def test_decidir_exige_autenticacao(client, cena):
    r = client.put(
        f"/api/v1/influencers/{cena.criador_id}/recommendations/0",
        json={"analysis_id": str(cena.analise_id), "decision": "accepted"},
    )
    assert r.status_code == 401


def test_apagar_a_analise_leva_a_decisao_junto(client, cena, app):
    _decidir(client, cena, 0, "accepted")
    with app.app_context():
        db.session.delete(db.session.get(AIAnalysis, cena.analise_id))
        db.session.commit()
        assert db.session.scalar(
            select(func.count()).select_from(RecommendationDecision)
            .where(RecommendationDecision.analysis_id == cena.analise_id)
        ) == 0
