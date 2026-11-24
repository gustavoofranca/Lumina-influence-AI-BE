"""Geração de relatórios PDF a partir dos dados reais da campanha.

Reaproveita o `dashboard_service.campaign_benchmarking` (B5) pra os dados por
criador e compõe o contexto do template. Renderiza HTML→PDF e salva em
storage/reports/{report_id}.pdf.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from flask import current_app
from jinja2 import Environment, select_autoescape
from sqlalchemy import func, select

from src.extensions import db
from src.models import (
    Campaign,
    Post,
    Report,
    ReportFormat,
)
from src.services import dashboard_service
from src.services import metric_service as M
from src.services.report_template import REPORT_HTML
from src.utils.brand import marca_data_uri
from src.utils.errors import NotFoundError, ValidationError
from src.utils.pdf_generator import render_pdf

logger = logging.getLogger(__name__)

SECTION_KEYS = ["kpis", "growth", "benchmark", "diagnostic", "video", "recommendations"]


def build_report_query(agency_id: uuid.UUID):
    """SELECT de relatórios da agência, do mais recente para o mais antigo."""
    return (
        select(Report)
        .where(Report.agency_id == agency_id)
        .order_by(Report.generated_at.desc())
    )

_jinja = Environment(autoescape=select_autoescape(["html", "xml"]))
_template = _jinja.from_string(REPORT_HTML)


# ==========================================================================
# Formatação
# ==========================================================================
def _fmt_compact(n: int) -> str:
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


def _fmt_brl(cents: int) -> str:
    return f"{(cents or 0) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _media(values: list[float | None], casas: int = 1) -> float | None:
    """Média apenas do que foi medido. Sem nenhuma medição, não há média (ADR-003)."""
    medidos = [v for v in values if v is not None]
    return round(sum(medidos) / len(medidos), casas) if medidos else None


def _fmt_pct(value: float | None) -> str:
    """Percentual para exibição; ausência de medição vira travessão, não `0%`."""
    return "—" if value is None else f"{value}%"


# ==========================================================================
# Contexto
# ==========================================================================
def build_report_context(
    *, campaign: Campaign, period_start: date, period_end: date, sections: list[str],
    title: str, generated_by: str,
) -> dict:
    """Monta o contexto do template: só compõe, quem consulta e calcula são os blocos."""
    dados = _consultar_periodo(campaign, period_start, period_end)
    resumo = _resumo(dados)
    return {
        "report_title": title,
        "brand_mark": marca_data_uri(),
        "campaign": {
            "brand_name": campaign.brand_name,
            "title": campaign.title,
        },
        "period_start": period_start.strftime("%d/%m/%Y"),
        "period_end": period_end.strftime("%d/%m/%Y"),
        "budget_brl": _fmt_brl(campaign.budget_brl_cents),
        "generated_by": generated_by,
        "generated_at": datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC"),
        "summary": resumo,
        "sections": [s for s in sections if s in SECTION_KEYS],
        "kpis": _kpis(dados, resumo),
        "kpis_detalhe": _kpis_detalhe(campaign, dados),
        "posts_tabela": _tabela_de_posts(dados),
        "growth": _crescimento(dados, resumo),
        "benchmark": _benchmark(dados.rows),
        "diagnostic": _diagnostico(dados.rows),
        # Vídeo — o que a IA ouviu, e não só o que concluiu.
        "video": _gather_video_analyses(dados.rows, dados.posts),
        # Das análises dos posts que entraram no período.
        "recommendations": _gather_recommendations(dados.rows, dados.posts),
    }


# --------------------------------------------------------------------------
# Consulta
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class _DadosDoPeriodo:
    """Tudo o que o relatório lê do banco para um intervalo, lido uma vez só."""

    rows: list[dict]
    posts: list[Post]
    posts_count: int

    @property
    def total_reach(self) -> int:
        return sum(r["total_reach"] for r in self.rows)

    @property
    def has_data(self) -> bool:
        # Sem post no período não há o que medir. A distinção precisa viajar no
        # contexto: quem renderiza não tem como separar "medimos zero" de "não
        # medimos" olhando só para os números. Mesmo princípio da ADR-002.
        return self.posts_count > 0


def _consultar_periodo(campaign: Campaign, period_start: date, period_end: date) -> _DadosDoPeriodo:
    bench = dashboard_service.campaign_benchmarking(
        campaign, period_start=period_start, period_end=period_end
    )
    return _DadosDoPeriodo(
        rows=bench["influencers"],
        posts=_campaign_posts(campaign.id, period_start, period_end),
        posts_count=_count_campaign_posts(campaign.id, period_start, period_end),
    )


# --------------------------------------------------------------------------
# Cálculo de cada bloco
# --------------------------------------------------------------------------
def _resumo(dados: _DadosDoPeriodo) -> dict:
    """Sumário executivo."""
    media_organica = _media([r["organic_pct"] for r in dados.rows])
    media_sentimento = _media([r["sentiment_index_pct"] for r in dados.rows])
    return {
        "influencer_count": len(dados.rows),
        "avg_organic_pct": media_organica,
        "avg_organic_pct_fmt": _fmt_pct(media_organica),
        "avg_sentiment_pct": media_sentimento,
        "avg_sentiment_pct_fmt": _fmt_pct(media_sentimento),
        "total_reach_fmt": _fmt_compact(dados.total_reach),
        "posts_count": dados.posts_count,
        "has_data": dados.has_data,
    }


def _kpis(dados: _DadosDoPeriodo, resumo: dict) -> list[dict]:
    """Cartões de KPI da campanha.

    `depends_on_posts` diz quais cartões perdem o sentido num período sem
    post. A contagem de criadores não é um deles: é fato do elenco da
    campanha, não medição do período.
    """
    media_engajamento = _media([r["engagement_rate"] for r in dados.rows], casas=2)
    return [
        {"label": "Criadores", "value": str(len(dados.rows)), "change": None,
         "depends_on_posts": False},
        {"label": "Alcance Total", "value": _fmt_compact(dados.total_reach), "change": None,
         "depends_on_posts": True},
        {"label": "Engajamento Médio", "value": _fmt_pct(media_engajamento), "change": None,
         "depends_on_posts": True},
        {"label": "Sentimento Médio", "value": resumo["avg_sentiment_pct_fmt"],
         "change": None, "depends_on_posts": True},
    ]


def _crescimento(dados: _DadosDoPeriodo, resumo: dict) -> list[dict]:
    """Orgânico contra pago por mês, só dos posts da campanha."""
    # Sem divisão medida, a coluna "orgânico" repetiria o total e "pago" diria
    # zero — as duas afirmações que a ADR-005 proíbe apresentar como coleta.
    sem_divisao = dados.has_data and resumo["avg_organic_pct"] is None
    return [
        {
            # O rótulo mensal sai de `%b`, que é inglês ("Aug") num PDF em português.
            "x": _MESES_PT.get(g["x"], g["x"]),
            # Cru para o gráfico da pré-visualização, formatado para o PDF.
            "organic": g["organic"],
            "paid": g["paid"],
            "organic_fmt": "—" if sem_divisao else _fmt_compact(g["organic"]),
            "paid_fmt": "—" if sem_divisao else _fmt_compact(g["paid"]),
        }
        for g in M.growth_trajectory(dados.posts, "90d")
    ]


def _benchmark(rows: list[dict]) -> list[dict]:
    """Uma linha por criador.

    Os valores crus servem a gráfico; os `_fmt` são o que PDF e pré-visualização
    exibem, para que a ausência de medição vire travessão nos dois e não
    "None%" num e "0%" no outro.
    """
    return [
        {
            "display_name": r["display_name"],
            "total_reach_fmt": _fmt_compact(r["total_reach"]),
            "organic_pct": r["organic_pct"],
            "organic_pct_fmt": _fmt_pct(r["organic_pct"]),
            "engagement_rate": r["engagement_rate"],
            "engagement_rate_fmt": _fmt_pct(r["engagement_rate"]),
            "sentiment_index_pct": r["sentiment_index_pct"],
            "sentiment_index_pct_fmt": _fmt_pct(r["sentiment_index_pct"]),
            "ai_score": r["ai_score"],
            "ai_score_fmt": "—" if r["ai_score"] is None else str(r["ai_score"]),
        }
        for r in rows
    ]


def _diagnosticavel(r: dict) -> bool:
    # Quem não tem as três notas no período não entra: uma frase montada sobre
    # zeros afirmaria "alinhamento parcial" e "bot baixa" sem nenhuma análise.
    return all(
        r[chave] is not None
        for chave in ("ai_score", "brand_coherence", "bot_probability", "sentiment_index_pct")
    )


def _nota_de_diagnostico(r: dict) -> str:
    alinhamento = "forte" if r["brand_coherence"] > 85 else "parcial"
    sentimento = "majoritariamente positivo" if r["sentiment_index_pct"] >= 80 else "misto"
    bot = "baixa" if r["bot_probability"] < 5 else "a monitorar"
    return (
        f"Análise indica alinhamento {alinhamento} com a marca, "
        f"sentimento {sentimento} "
        f"e probabilidade de bot {bot}."
    )


def _diagnostico(rows: list[dict]) -> list[dict]:
    """Os dois criadores de maior nota de IA.

    Sai das próprias linhas do benchmarking, que já vêm filtradas pelo período.
    Reler as análises do criador aqui descrevia a vida inteira dele sob uma
    capa que promete um intervalo.
    """
    melhores = sorted(filter(_diagnosticavel, rows), key=lambda r: r["ai_score"], reverse=True)
    return [
        {
            "display_name": r["display_name"], "niche": r["niche"] or "—",
            "brand_coherence": r["brand_coherence"], "bot_probability": r["bot_probability"],
            "note": _nota_de_diagnostico(r),
        }
        for r in melhores[:2]
    ]


def _kpis_detalhe(campaign: Campaign, dados: _DadosDoPeriodo) -> list[dict]:
    """Engajamento bruto e custo.

    Com poucos criadores o relatório ficava com meia página em branco, e esses
    números já estavam no banco — é dado medido, não preenchimento. O custo por
    mil só existe com orçamento e alcance: sem um dos dois, travessão, nunca
    "R$ 0,00".
    """
    def soma(campo: str) -> int:
        return sum(getattr(p, campo) or 0 for p in dados.posts)

    alcance = dados.total_reach
    cpm = (
        "R$ " + _fmt_brl(round(campaign.budget_brl_cents * 1000 / alcance))
        if dados.has_data and alcance > 0 and campaign.budget_brl_cents > 0 else "—"
    )
    return [
        {"label": "Curtidas", "value": _fmt_compact(soma("likes"))},
        {"label": "Comentários", "value": _fmt_compact(soma("comments_count"))},
        {"label": "Compartilhamentos", "value": _fmt_compact(soma("shares"))},
        {"label": "Custo por mil alcançados", "value": cpm},
    ]


def _legenda_curta(caption: str | None) -> str:
    legenda = " ".join((caption or "").split())
    if len(legenda) > 70:
        return legenda[:70] + "…"
    return legenda or "—"


def _tabela_de_posts(dados: _DadosDoPeriodo) -> list[dict]:
    """Os posts mais recentes do período, um por linha."""
    nomes = {r["influencer_id"]: r["display_name"] for r in dados.rows if r.get("influencer_id")}
    recentes = sorted(dados.posts, key=lambda x: x.posted_at, reverse=True)
    return [
        {
            "data": p.posted_at.strftime("%d/%m/%Y"),
            "criador": nomes.get(str(p.social_account.influencer_id), "—")
                       if p.social_account else "—",
            "legenda": _legenda_curta(p.caption),
            "alcance": _fmt_compact(p.reach_total) if p.reach_total else "—",
            "curtidas": _fmt_compact(p.likes),
            "comentarios": _fmt_compact(p.comments_count),
            "compartilhamentos": _fmt_compact(p.shares),
            "salvos": _fmt_compact(p.saves),
        }
        for p in recentes[:LIMITE_DE_POSTS_NA_TABELA]
    ]


LIMITE_DE_POSTS_NA_TABELA = 15

_MESES_PT = dict(zip(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"],
))


def _posts_in_period(campaign_id: uuid.UUID, period_start: date, period_end: date):
    """Posts da campanha dentro do intervalo declarado na capa do relatório."""
    return (
        select(Post)
        .where(Post.campaign_id == campaign_id)
        .where(func.date(Post.posted_at) >= period_start)
        .where(func.date(Post.posted_at) <= period_end)
    )


def _campaign_posts(campaign_id: uuid.UUID, period_start: date, period_end: date) -> list[Post]:
    return list(db.session.scalars(_posts_in_period(campaign_id, period_start, period_end)).all())


def _count_campaign_posts(campaign_id: uuid.UUID, period_start: date, period_end: date) -> int:
    subq = _posts_in_period(campaign_id, period_start, period_end).subquery()
    return int(db.session.scalar(select(func.count()).select_from(subq)) or 0)


LIMITE_DE_RECOMENDACOES = 5

SEM_RECOMENDACAO = {
    "title": "Manter monitoramento contínuo",
    "description": (
        "Sem recomendações de IA registradas para o período. "
        "Rode análises nos posts da campanha."
    ),
}


def _analises_do_periodo(
    rows: list[dict],
    por_influencer: dict,
    ids_do_periodo: set,
) -> Iterator:
    """As análises dos participantes, na ordem das linhas, só as do intervalo.

    Devolve o model de análise sem nomeá-lo no tipo: `report_service` não
    importa model de outro módulo (regra ARQ-01), e o agrupamento já chega
    pronto de `metric_service`.
    """
    for linha in rows:
        for analise in por_influencer.get(uuid.UUID(linha["influencer_id"]), []):
            if analise.post_id in ids_do_periodo:
                yield analise


def _sugestoes_da_analise(analise) -> Iterator[tuple[str, str]]:
    """Pares (título, descrição) utilizáveis de uma análise.

    O campo vem do modelo generativo e é JSON livre: pode trazer string solta,
    número ou objeto sem título. O que não tem título não vira recomendação —
    um item sem rótulo apareceria no PDF como marcador vazio.
    """
    for item in analise.recommendations or []:
        if not isinstance(item, dict):
            continue
        titulo = item.get("title", "")
        if titulo:
            yield titulo, item.get("description", "")


def _gather_recommendations(rows: list[dict], posts: list[Post]) -> list[dict]:
    """Recomendações das análises dos posts do período, não da vida do criador.

    Ler todas as análises de cada participante fazia um relatório de março
    listar sugestões geradas em janeiro, sob uma capa que promete março. Busca
    em lote e filtra pelos posts que entraram no intervalo.

    Duas coisas diferentes limitam a lista, e vale não confundi-las:

    - O `break` interrompe a leitura assim que já há recomendações suficientes.
      É **economia de trabalho e nada mais** — como a lista é truncada no fim
      de qualquer jeito, tirá-lo não muda uma vírgula da saída. Foi conferido
      removendo-o: o teste continua passando.
    - O fatiamento no `return` é o que de fato define o que sai, e ele **pode**
      cortar uma análise no meio, se a última a entrar trouxer mais itens do
      que cabe.
    """
    ids_do_periodo = {p.id for p in posts}
    por_influencer = M.fetch_analyses_by_influencer(
        [uuid.UUID(r["influencer_id"]) for r in rows]
    )

    recomendacoes: list[dict] = []
    titulos_vistos: set[str] = set()
    for analise in _analises_do_periodo(rows, por_influencer, ids_do_periodo):
        for titulo, descricao in _sugestoes_da_analise(analise):
            if titulo in titulos_vistos:
                continue
            titulos_vistos.add(titulo)
            recomendacoes.append({"title": titulo, "description": descricao})
        if len(recomendacoes) >= LIMITE_DE_RECOMENDACOES:
            break

    if not recomendacoes:
        # Cópia: o original montava o dicionário a cada chamada, e quem
        # consome o contexto do relatório não deve conseguir escrever numa
        # constante do módulo.
        return [dict(SEM_RECOMENDACAO)]
    return recomendacoes[:LIMITE_DE_RECOMENDACOES]


# Quantas análises de vídeo entram no documento. Duas cabem numa página sem
# empurrar as recomendações para a seguinte, e o relatório é um resumo — quem
# quer o conjunto inteiro abre a aba do criador.
LIMITE_DE_VIDEOS = 2

# Teto do trecho de transcrição impresso. A transcrição inteira de um vídeo de
# um minuto passa de três mil caracteres e engoliria a página; o corte é
# anunciado com reticências para ninguém ler o trecho como fala completa.
LIMITE_DA_TRANSCRICAO = 600


def _trecho_da_transcricao(texto: str) -> tuple[str, bool]:
    """Corta a transcrição no limite, sem partir palavra. Diz se cortou."""
    limpo = " ".join((texto or "").split())
    if len(limpo) <= LIMITE_DA_TRANSCRICAO:
        return limpo, False
    corte = limpo[:LIMITE_DA_TRANSCRICAO]
    espaco = corte.rfind(" ")
    if espaco > 0:
        corte = corte[:espaco]
    return corte, True


def _gather_video_analyses(rows: list[dict], posts: list[Post]) -> list[dict]:
    """As análises multimodais do período — as que o modelo assistiu, não só leu.

    O relatório já trazia o que a IA *concluiu* sobre cada criador, em número:
    coerência, sentimento, probabilidade de bot. Não trazia nada do que ela
    *ouviu*. A transcrição é a única parte do documento em que dá para conferir
    o trabalho do modelo contra o vídeo — sem ela, o leitor precisa aceitar as
    notas no escuro.

    O que distingue uma análise multimodal é ter `transcript_text`: só o caminho
    com vídeo o preenche. Filtrar por `model_version` seria mais direto, mas
    quebraria na primeira vez que o sufixo mudasse.
    """
    ids_do_periodo = {p.id for p in posts}
    legenda_por_post = {p.id: p.caption for p in posts}
    nome_por_influencer = {r["influencer_id"]: r["display_name"] for r in rows}
    por_influencer = M.fetch_analyses_by_influencer(
        [uuid.UUID(r["influencer_id"]) for r in rows]
    )

    videos: list[dict] = []
    for linha in rows:
        for analise in por_influencer.get(uuid.UUID(linha["influencer_id"]), []):
            if analise.post_id not in ids_do_periodo:
                continue
            if not (analise.transcript_text or "").strip():
                continue
            trecho, cortado = _trecho_da_transcricao(analise.transcript_text)
            videos.append({
                "display_name": nome_por_influencer.get(linha["influencer_id"], "—"),
                "caption": (legenda_por_post.get(analise.post_id) or "").strip(),
                # `None` e não zero quando o modelo não devolveu a nota: é a
                # ADR-003 — ausência de medição não vira medição de zero.
                "script_score": analise.script_score,
                "script_score_fmt": (
                    f"{analise.script_score:.0f}" if analise.script_score is not None else "—"
                ),
                "sentiment_label": analise.sentiment_label.value,
                "transcript": trecho,
                "transcript_truncated": cortado,
                "key_phrases": [
                    f for f in (analise.key_phrases or []) if isinstance(f, str)
                ][:6],
                "analyzed_at": analise.analyzed_at.strftime("%d/%m/%Y"),
                "model_version": analise.model_version,
            })
            if len(videos) >= LIMITE_DE_VIDEOS:
                return videos
    return videos


# ==========================================================================
# Geração
# ==========================================================================
def _storage_dir() -> Path:
    base = Path(current_app.root_path).parent / "storage" / "reports"
    base.mkdir(parents=True, exist_ok=True)
    return base


def generate_report(
    *, agency_id: uuid.UUID, generated_by_user_id: uuid.UUID | None, generated_by_name: str,
    campaign_id: uuid.UUID, title: str, period_start: date, period_end: date, sections: list[str],
) -> Report:
    campaign = db.session.scalar(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.agency_id == agency_id)
    )
    if campaign is None:
        raise NotFoundError("Campaign não encontrada")
    if period_end < period_start:
        raise ValidationError("period_end não pode ser anterior a period_start")

    report = Report(
        agency_id=agency_id,
        campaign_id=campaign_id,
        generated_by_user_id=generated_by_user_id,
        title=title,
        period_start=period_start,
        period_end=period_end,
        format=ReportFormat.PDF,
        sections={"included": [s for s in sections if s in SECTION_KEYS]},
        generated_at=datetime.now(timezone.utc),
    )
    db.session.add(report)
    db.session.flush()  # garante report.id

    context = build_report_context(
        campaign=campaign, period_start=period_start, period_end=period_end,
        sections=sections, title=title, generated_by=generated_by_name,
    )
    html = _template.render(**context)
    pdf_bytes = render_pdf(html)

    path = _storage_dir() / f"{report.id}.pdf"
    path.write_bytes(pdf_bytes)
    report.pdf_url = f"/api/v1/reports/{report.id}/download"
    db.session.commit()

    logger.info("Relatório gerado: id=%s campanha=%s bytes=%d", report.id, campaign_id, len(pdf_bytes))
    return report


def report_pdf_path(report: Report) -> Path:
    return _storage_dir() / f"{report.id}.pdf"


def ensure_pdf(report: Report) -> Path:
    """Garante que o PDF existe no disco; gera sob demanda se faltar.

    Relatórios seedados (B2) têm metadados mas não o arquivo — esta função
    materializa o PDF na primeira vez que é baixado.
    """
    path = report_pdf_path(report)
    if path.exists():
        return path
    campaign = db.session.get(Campaign, report.campaign_id) if report.campaign_id else None
    if campaign is None:
        raise NotFoundError("Campanha do relatório não existe mais")
    sections = (report.sections or {}).get("included") or SECTION_KEYS
    context = build_report_context(
        campaign=campaign, period_start=report.period_start, period_end=report.period_end,
        sections=sections, title=report.title, generated_by="Equipe Lumina",
    )
    html = _template.render(**context)
    path.write_bytes(render_pdf(html))
    logger.info("PDF gerado sob demanda: report=%s", report.id)
    return path
