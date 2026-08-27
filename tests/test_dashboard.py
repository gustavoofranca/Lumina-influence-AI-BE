"""Testes dos endpoints de dashboard (B5).

Usa o seed completo (posts + análises reais) pra validar as agregações.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from src.extensions import db
from src.models import (
    Campaign,
    CampaignInfluencer,
    Influencer,
    InfluencerStatus,
    Post,
    User,
    UserRole,
)
from src.seed.seed_data import seed_clear, seed_run
from src.utils.jwt_utils import issue_token_pair


class Ctx:
    pass


@pytest.fixture()
def seeded(app):
    with app.app_context():
        seed_clear()
        seed_run()

        admin = db.session.scalar(
            select(User).where(User.role == UserRole.ADMIN)
        )
        influencer = db.session.scalar(select(Influencer))
        campaign = db.session.scalar(select(Campaign))

        c = Ctx()
        c.header = {"Authorization": f"Bearer {issue_token_pair(admin)['access_token']}"}
        c.influencer_id = str(influencer.id)
        c.campaign_id = str(campaign.id)
        yield c

        seed_clear()


# --------------------------------------------------------------------------
# /dashboard/overview
# --------------------------------------------------------------------------
def test_overview_shape(client, seeded):
    r = client.get("/api/v1/dashboard/overview?period=30d", headers=seeded.header)
    assert r.status_code == 200
    body = r.get_json()
    data = body["data"]

    # KPIs
    assert set(data["kpis"].keys()) == {"roi", "engagement_rate", "cac", "active_influencers"}
    assert "value_pct" in data["kpis"]["engagement_rate"]
    assert data["kpis"]["active_influencers"]["value"] >= 1

    # Estruturas agregadas
    assert isinstance(data["growth_trajectory"], list)
    assert isinstance(data["top_performing"], list)
    assert len(data["top_performing"]) <= 6
    assert body["meta"]["period"] == "30d"


def test_overview_top_performing_sorted(client, seeded):
    r = client.get("/api/v1/dashboard/overview", headers=seeded.header)
    cards = r.get_json()["data"]["top_performing"]
    scores = [c["resonance_score"] for c in cards]
    assert scores == sorted(scores, reverse=True)
    for c in cards:
        assert c["viral_potential"] in {"high", "medium", "low"}


def test_overview_featured_diagnosis_present(client, seeded):
    r = client.get("/api/v1/dashboard/overview", headers=seeded.header)
    fd = r.get_json()["data"]["featured_diagnosis"]
    # 143 análises seedadas → deve existir
    assert fd is not None
    assert "influencer_name" in fd
    assert "pills" in fd


def test_overview_period_filter_changes_buckets(client, seeded):
    r7 = client.get("/api/v1/dashboard/overview?period=7d", headers=seeded.header)
    r90 = client.get("/api/v1/dashboard/overview?period=90d", headers=seeded.header)
    assert r7.status_code == 200 and r90.status_code == 200
    # 90d cobre mais posts que 7d → pelo menos não menos buckets de modo geral
    assert isinstance(r7.get_json()["data"]["growth_trajectory"], list)


def test_overview_invalid_campaign_id_422(client, seeded):
    r = client.get(
        "/api/v1/dashboard/overview?campaign_id=not-a-uuid", headers=seeded.header
    )
    assert r.status_code == 422


def test_overview_requires_auth(client, seeded):
    r = client.get("/api/v1/dashboard/overview")
    assert r.status_code == 401


# --------------------------------------------------------------------------
# /dashboard/network-density
# --------------------------------------------------------------------------
def test_network_density(client, seeded):
    r = client.get("/api/v1/dashboard/network-density", headers=seeded.header)
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data["total"] == 15
    assert data["connected"] == 15  # todos têm conta social
    assert data["value"] == 100


# --------------------------------------------------------------------------
# /influencers/:id/analysis
# --------------------------------------------------------------------------
def test_influencer_analysis_shape(client, seeded):
    r = client.get(
        f"/api/v1/influencers/{seeded.influencer_id}/analysis", headers=seeded.header
    )
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert "influencer" in data
    assert set(data["diagnostic_kpis"].keys()) == {
        "brand_coherence",
        "sentiment_index_pct",
        "safety_rating",
        "bot_probability",
    }
    assert "audience_integrity" in data
    assert "neural_confidence" in data
    assert isinstance(data["sentiment_clusters"], list)
    assert isinstance(data["keywords"], list)


def test_influencer_analysis_audience_integrity_sums_100(client, seeded):
    r = client.get(
        f"/api/v1/influencers/{seeded.influencer_id}/analysis", headers=seeded.header
    )
    ai = r.get_json()["data"]["audience_integrity"]
    total = ai["organic"] + ai["suspicious"] + ai["bots"]
    assert abs(total - 100) <= 0.5


def test_analysis_other_agency_404(client, seeded):
    r = client.get(
        f"/api/v1/influencers/{uuid.uuid4()}/analysis", headers=seeded.header
    )
    assert r.status_code == 404


# --------------------------------------------------------------------------
# /influencers/:id/posts
# --------------------------------------------------------------------------
def test_influencer_posts(client, seeded):
    r = client.get(
        f"/api/v1/influencers/{seeded.influencer_id}/posts?limit=5", headers=seeded.header
    )
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["data"]) <= 5
    if body["data"]:
        p = body["data"][0]
        assert set(p.keys()) >= {
            "id", "caption", "posted_at", "platform", "reach_total",
            "sentiment_score", "bot_probability",
        }
    assert body["meta"]["limit"] == 5


# --------------------------------------------------------------------------
# /campaigns/:id/benchmarking
# --------------------------------------------------------------------------
def test_campaign_benchmarking_shape(client, seeded):
    r = client.get(
        f"/api/v1/campaigns/{seeded.campaign_id}/benchmarking", headers=seeded.header
    )
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert "campaign" in data
    assert isinstance(data["influencers"], list)
    assert "radar" in data
    assert data["radar"]["dimensions"] == ["reach", "engagement", "sentiment", "coherence", "organic"]
    # cada série do radar tem 5 valores (1 por dimensão)
    for serie in data["radar"]["series"]:
        assert len(serie["values"]) == 5


def test_benchmarking_other_agency_404(client, seeded):
    r = client.get(
        f"/api/v1/campaigns/{uuid.uuid4()}/benchmarking", headers=seeded.header
    )
    assert r.status_code == 404


def test_benchmarking_row_traz_identidade_do_influencer(client, seeded):
    """A tela de participantes precisa de identidade, não só métrica (B11)."""
    r = client.get(
        f"/api/v1/campaigns/{seeded.campaign_id}/benchmarking", headers=seeded.header
    )
    rows = r.get_json()["data"]["influencers"]
    assert rows, "campanha seedada deve ter participantes"

    for row in rows:
        assert {
            "influencer_id", "display_name", "handle", "niche", "status",
            "platforms", "followers", "posts_count", "deliverables",
            "brand_coherence", "bot_probability",
        } <= set(row)
        assert row["status"] in {s.value for s in InfluencerStatus}
        assert isinstance(row["platforms"], list)
        assert row["followers"] >= 0
        assert row["posts_count"] >= 0


def test_benchmarking_nao_expoe_token_de_conta_social(client, seeded):
    """Contas sociais carregam token cifrado — ele não pode vazar na resposta."""
    r = client.get(
        f"/api/v1/campaigns/{seeded.campaign_id}/benchmarking", headers=seeded.header
    )
    assert "_encrypted" not in r.get_data(as_text=True)


# --------------------------------------------------------------------------
# participantes de campanha
# --------------------------------------------------------------------------
def test_lista_de_campanhas_traz_participantes(client, seeded):
    r = client.get("/api/v1/campaigns", headers=seeded.header)
    assert r.status_code == 200
    items = r.get_json()["data"]
    assert items

    for camp in items:
        assert isinstance(camp["participants"], list)
        for p in camp["participants"]:
            assert set(p) == {"influencer_id", "display_name"}

    assert any(c["participants"] for c in items)


def test_detalhe_da_campanha_traz_participantes(client, seeded):
    r = client.get(f"/api/v1/campaigns/{seeded.campaign_id}", headers=seeded.header)
    assert r.status_code == 200
    assert isinstance(r.get_json()["data"]["participants"], list)


def test_participantes_batem_com_o_benchmarking(client, seeded):
    """Duas rotas, uma verdade: a associativa é a mesma."""
    detail = client.get(
        f"/api/v1/campaigns/{seeded.campaign_id}", headers=seeded.header
    ).get_json()["data"]
    bench = client.get(
        f"/api/v1/campaigns/{seeded.campaign_id}/benchmarking", headers=seeded.header
    ).get_json()["data"]

    assert {p["influencer_id"] for p in detail["participants"]} == {
        r["influencer_id"] for r in bench["influencers"]
    }


def test_benchmarking_nao_atribui_posts_de_outra_campanha(client, seeded):
    """Campanha sem post próprio reporta zero, não o histórico do criador.

    Antes havia fallback para todos os posts do influencer: uma campanha que
    nem começou exibia alcance e engajamento como se tivesse performado.
    """
    with client.application.app_context():
        camp = db.session.scalar(
            select(Campaign).where(
                ~Campaign.id.in_(select(Post.campaign_id).where(Post.campaign_id.is_not(None)))
            )
        )
        assert camp is not None, "o seed precisa de uma campanha sem posts"
        assert db.session.scalar(
            select(func.count(CampaignInfluencer.id)).where(
                CampaignInfluencer.campaign_id == camp.id
            )
        ) > 0, "e ela precisa ter participantes, senão o teste não prova nada"
        camp_id = str(camp.id)

    rows = client.get(
        f"/api/v1/campaigns/{camp_id}/benchmarking", headers=seeded.header
    ).get_json()["data"]["influencers"]

    assert rows, "os participantes continuam listados"
    for row in rows:
        assert row["posts_count"] == 0
        # Alcance é soma: sem post, soma zero de verdade.
        assert row["total_reach"] == 0
        # Engajamento é razão: sem post não foi medido, e zero afirmaria medição.
        assert row["engagement_rate"] is None
        assert row["organic_pct"] is None
        # O custo contratado é real e independe de já ter havido post.
        assert row["cost_brl_cents"] > 0


# --------------------------------------------------------------------------
# Custo em round trips — N+1 no overview
# --------------------------------------------------------------------------
def _contar_queries(app, funcao):
    """Executa `funcao` contando as queries emitidas no engine."""
    from sqlalchemy import event

    contagem = {"n": 0}
    engine = db.engine

    def contar(*_args, **_kwargs):
        contagem["n"] += 1

    event.listen(engine, "before_cursor_execute", contar)
    try:
        funcao()
    finally:
        event.remove(engine, "before_cursor_execute", contar)
    return contagem["n"]


def test_overview_nao_consulta_por_influenciador(app, seeded):
    """O custo do overview não pode crescer com o número de criadores.

    Cada query é um round trip. Em banco local a diferença some no ruído; contra
    instância gerenciada, 70 round trips viraram 15 segundos de resposta —
    medido na carga da B12. O teto abaixo é folgado de propósito: ele existe
    para pegar a volta do N+1, não para congelar a implementação.
    """
    from src.models import Agency
    from src.services import dashboard_service

    with app.app_context():
        agencia = db.session.scalar(select(Agency))
        total_influenciadores = db.session.scalar(
            select(func.count(Influencer.id)).where(Influencer.agency_id == agencia.id)
        )
        assert total_influenciadores >= 5, "seed pequeno demais para revelar N+1"

        n = _contar_queries(
            app, lambda: dashboard_service.overview(agencia.id, period="30d")
        )

    assert n <= 20, (
        f"{n} queries para {total_influenciadores} criadores — o overview voltou "
        "a consultar por influenciador em vez de buscar em lote"
    )


# --------------------------------------------------------------------------
# /influencers/:id/analyses — histórico do criador
# --------------------------------------------------------------------------
def test_historico_de_analises_do_criador(client, seeded):
    """A aba Histórico existe no front e não tinha endpoint que a alimentasse."""
    r = client.get(f"/api/v1/influencers/{seeded.influencer_id}/analyses",
                   headers=seeded.header)
    assert r.status_code == 200
    itens = r.get_json()["data"]
    assert itens, "o seed tem análises para este criador"

    primeiro = itens[0]
    for campo in ("analysis_id", "post_id", "analyzed_at", "platform",
                  "brand_coherence", "sentiment_index_pct"):
        assert campo in primeiro, campo

    datas = [i["analyzed_at"] for i in itens]
    assert datas == sorted(datas, reverse=True), "mais recente primeiro"


def test_historico_de_criador_de_outra_agencia_404(client, seeded, app):
    from src.models import Agency, Influencer, InfluencerStatus

    with app.app_context():
        outra = Agency(name="Outra")
        db.session.add(outra)
        db.session.flush()
        alheio = Influencer(agency_id=outra.id, display_name="Alheio",
                            status=InfluencerStatus.ACTIVE)
        db.session.add(alheio)
        db.session.commit()
        alheio_id = str(alheio.id)

    r = client.get(f"/api/v1/influencers/{alheio_id}/analyses", headers=seeded.header)
    assert r.status_code == 404


def test_engajamento_sem_post_no_periodo_vem_nulo(client, seeded, app):
    """Zero por cento afirma engajamento medido; a ausência de post não mediu nada.

    ROI e CAC já devolvem null nessa situação, por decisão da ADR-002. O
    engajamento devolvia 0, e a tela mostrava "0%" ao lado de dois travessões —
    o mesmo dado ausente contado de duas formas diferentes.
    """
    r = client.get("/api/v1/dashboard/overview?period=7d", headers=seeded.header)
    kpis_com_dados = r.get_json()["data"]["kpis"]
    assert kpis_com_dados["engagement_rate"]["value_pct"] is not None

    from src.models import Agency, Post
    from src.services import dashboard_service

    with app.app_context():
        agencia = db.session.scalar(select(Agency))
        # Sem nenhum post no período, não há o que medir.
        for p in db.session.scalars(select(Post)).all():
            db.session.delete(p)
        db.session.commit()
        kpis = dashboard_service.overview(agencia.id, period="30d")["kpis"]

    assert kpis["engagement_rate"]["value_pct"] is None
    assert kpis["engagement_rate"]["change"] is None
    # A contagem de criadores é fato do elenco, não medição do período.
    assert kpis["active_influencers"]["value"] >= 0


# ==========================================================================
# Ausência de dado nunca vira zero (ADR-003)
# ==========================================================================
def test_metricas_de_performance_sem_base_vem_nulas(app):
    """Sem post não há proporção a informar — mas há soma, e soma vazia é zero.

    A distinção importa: `organic` é um total de alcance, e nenhum alcance
    somado dá zero de verdade. `organic_pct` é uma proporção sobre um total
    inexistente, e afirmar "0% do alcance foi orgânico" é medir o que não houve.
    """
    from src.services import metric_service as M

    assert M.engagement_rate([]) is None

    split = M.reach_split([])
    assert split["organic"] == 0
    assert split["paid"] == 0
    assert split["total"] == 0
    assert split["organic_pct"] is None
    assert split["paid_pct"] is None


def test_scores_derivados_de_metrica_ausente_tambem_vem_nulos(app):
    """Score composto sem nenhuma parcela medida não é zero, é indefinido."""
    from src.services import metric_service as M

    assert M.resonance_score(None, None, None) is None
    assert M.viral_potential(None) is None

    # Com uma parcela medida, o score existe e usa só o que foi medido.
    assert M.resonance_score(None, 80.0, None) == 80.0
    assert M.resonance_score(6.0, None, None) == 50.0


def test_criador_sem_post_nao_declara_engajamento_zero(client, seeded, app):
    """O criador sem post mostrava 0,0% de engajamento ao lado de sentimento em —.

    Era o mesmo dado ausente contado de duas formas na mesma tela.
    """
    with app.app_context():
        influencer = db.session.scalar(select(Influencer))
        for p in db.session.scalars(
            select(Post).join(Post.social_account).where(
                Post.social_account_id.in_(
                    [sa.id for sa in influencer.social_accounts]
                )
            )
        ).all():
            db.session.delete(p)
        db.session.commit()
        inf_id = str(influencer.id)

    r = client.get(f"/api/v1/influencers/{inf_id}?enriched=true", headers=seeded.header)
    assert r.status_code == 200
    m = r.get_json()["data"]["metrics"]

    assert m["engagement_rate"] is None
    assert m["organic_pct"] is None
    assert m["paid_pct"] is None


def test_ranking_nao_quebra_com_criador_sem_metrica(client, seeded, app):
    """Ordenar por um score que pode ser nulo não pode levantar TypeError."""
    with app.app_context():
        influencer = db.session.scalar(select(Influencer))
        for p in db.session.scalars(
            select(Post).where(
                Post.social_account_id.in_(
                    [sa.id for sa in influencer.social_accounts]
                )
            )
        ).all():
            db.session.delete(p)
        db.session.commit()

    r = client.get("/api/v1/dashboard/overview", headers=seeded.header)
    assert r.status_code == 200
    top = r.get_json()["data"]["top_performing"]
    assert top, "o ranking continua sendo devolvido"
    # Quem não tem métrica não pode aparecer à frente de quem tem.
    medidos = [c["resonance_score"] for c in top if c["resonance_score"] is not None]
    assert medidos == sorted(medidos, reverse=True)


def test_criador_sem_analise_nao_afirma_audiencia_organica(client, seeded, app):
    """Sem análise, bot_probability era lido como 0 e a tela dizia "100% orgânico".

    Zero inventado já é ruim; este inventava um número favorável ao criador,
    que é exatamente o que um sistema de auditoria não pode fazer.
    """
    from src.models import AIAnalysis

    with app.app_context():
        influencer = db.session.scalar(select(Influencer))
        for a in db.session.scalars(select(AIAnalysis)).all():
            db.session.delete(a)
        db.session.commit()
        inf_id = str(influencer.id)

    r = client.get(f"/api/v1/influencers/{inf_id}/analysis", headers=seeded.header)
    assert r.status_code == 200
    data = r.get_json()["data"]

    assert data["audience_integrity"] is None
    assert data["neural_confidence"] == []


def test_analise_devolve_a_transcricao_quando_existe(client, seeded, app):
    """A transcrição estava no banco e não chegava à tela.

    111 das análises do seed têm `transcript_text`, mas o payload de
    /influencers/:id/analysis não trazia o campo — o componente de transcrição
    do front mostrava estado vazio para dado que existia.
    """
    from src.models import AIAnalysis, SocialAccount

    with app.app_context():
        # Zera as transcrições e planta uma só, para saber qual deve voltar —
        # o seed já traz várias, e a mais recente venceria por acaso.
        todas = db.session.scalars(select(AIAnalysis)).all()
        for a in todas:
            a.transcript_text = None
        alvo = todas[0]
        alvo.transcript_text = "Testei por semanas e a diferença é absurda."
        alvo.key_phrases = ["diferença absurda"]
        post = db.session.get(Post, alvo.post_id)
        conta = db.session.get(SocialAccount, post.social_account_id)
        db.session.commit()
        inf_id = str(conta.influencer_id)

    r = client.get(f"/api/v1/influencers/{inf_id}/analysis", headers=seeded.header)
    assert r.status_code == 200
    transcript = r.get_json()["data"]["transcript"]

    assert transcript is not None
    assert transcript["text"].startswith("Testei por semanas")
    assert transcript["key_phrases"] == ["diferença absurda"]
    assert transcript["analyzed_at"]


def test_analise_sem_transcricao_devolve_nulo(client, seeded, app):
    """Análise só de texto não transcreve nada — e nulo é diferente de vazio."""
    from src.models import AIAnalysis

    with app.app_context():
        influencer = db.session.scalar(select(Influencer))
        for a in db.session.scalars(select(AIAnalysis)).all():
            a.transcript_text = None
        db.session.commit()
        inf_id = str(influencer.id)

    r = client.get(f"/api/v1/influencers/{inf_id}/analysis", headers=seeded.header)
    assert r.get_json()["data"]["transcript"] is None


def test_analise_devolve_a_trajetoria_de_crescimento_do_criador(client, seeded, app):
    """A aba Visão Geral tinha o gráfico pronto e dizia que a API não servia isto."""
    with app.app_context():
        inf_id = str(db.session.scalar(select(Influencer)).id)

    r = client.get(f"/api/v1/influencers/{inf_id}/analysis", headers=seeded.header)
    growth = r.get_json()["data"]["growth_trajectory"]

    assert isinstance(growth, list) and growth, "o criador do seed tem posts"
    for bucket in growth:
        assert {"x", "organic", "paid"} <= set(bucket)
    # É a série deste criador, não a da agência: o alcance somado não pode
    # passar do alcance total dele.
    total_serie = sum(b["organic"] + b["paid"] for b in growth)
    reach = r.get_json()["data"]["reach_split"]["total"]
    assert total_serie <= reach


def test_pills_do_diagnostico_carregam_o_valor_que_as_justifica(client, seeded):
    """Sem o valor no payload, o rótulo escrevia um número fixo.

    "85% Positive Sentiment" aparecia para qualquer criador, contradizendo o
    índice de sentimento que a própria tela dele mostrava.
    """
    r = client.get("/api/v1/dashboard/overview", headers=seeded.header)
    destaque = r.get_json()["data"]["featured_diagnosis"]

    assert destaque["pills"], "o seed tem análise com pelo menos uma pill"
    for pill in destaque["pills"]:
        assert "value_pct" in pill, f"pill {pill['key']} sem o número que a justifica"
        assert isinstance(pill["value_pct"], (int, float))
