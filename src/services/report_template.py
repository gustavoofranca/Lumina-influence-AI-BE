"""Template HTML do relatório PDF (compatível com xhtml2pdf).

Layout A4 espelhando o ReportPreview do front: capa + sumário executivo, depois
as seções selecionadas (kpis, growth, benchmark, diagnostic, recommendations).
xhtml2pdf não suporta flexbox/grid — usamos tabelas e CSS básico.
"""
from __future__ import annotations

REPORT_HTML = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<style>
  @page {
    size: a4;
    margin: 1.6cm 1.4cm 1.4cm 1.4cm;
    @frame footer_frame {
      -pdf-frame-content: footer_content;
      bottom: 0.8cm; left: 1.4cm; right: 1.4cm; height: 1cm;
    }
  }
  body { font-family: Helvetica, Arial, sans-serif; color: #0F172A; font-size: 10pt; }
  .brandbar { border-bottom: 2px solid #7C3AED; padding-bottom: 6px; margin-bottom: 14px; }
  .brandbar .logo { color: #7C3AED; font-size: 13pt; font-weight: bold; }
  .brandbar .brand { color: #64748B; font-size: 8pt; text-transform: uppercase; letter-spacing: 1px; }
  .eyebrow { color: #7C3AED; font-size: 8pt; font-weight: bold; text-transform: uppercase; letter-spacing: 2px; }
  h1.cover { font-size: 26pt; font-weight: bold; margin: 6px 0 4px 0; color: #0F172A; }
  .desc { color: #475569; font-size: 10pt; line-height: 1.5; }
  .meta-table td { padding: 8px 6px; border-top: 1px solid #E2E8F0; vertical-align: top; }
  .meta-label { color: #64748B; font-size: 7.5pt; text-transform: uppercase; letter-spacing: 1px; }
  .meta-value { color: #0F172A; font-size: 10pt; font-weight: bold; }
  h2.section { font-size: 12pt; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px;
               border-bottom: 2px solid #7C3AED; padding-bottom: 4px; margin: 0 0 8px 0; }
  .section-wrap { margin-bottom: 18px; }
  table.data { width: 100%; border-collapse: collapse; font-size: 9pt; }
  table.data th { text-align: left; color: #64748B; font-size: 7.5pt; text-transform: uppercase;
                  letter-spacing: 0.5px; border-bottom: 1px solid #CBD5E1; padding: 5px 4px; }
  table.data td { padding: 6px 4px; border-bottom: 1px solid #EEF2F7; }
  .num { text-align: right; }
  .score { color: #7C3AED; font-weight: bold; }
  .kpi-box { background-color: #F8FAFC; border: 1px solid #E2E8F0; padding: 8px; }
  .kpi-label { color: #64748B; font-size: 7pt; text-transform: uppercase; letter-spacing: 0.5px; }
  .kpi-value { font-size: 15pt; font-weight: bold; color: #0F172A; }
  .pos { color: #16A34A; } .neg { color: #E11D48; }
  .card { background-color: #F8FAFC; border: 1px solid #E2E8F0; padding: 8px; margin-bottom: 6px; }
  .muted { color: #64748B; font-size: 8.5pt; }
  ol.recs { padding-left: 16px; }
  ol.recs li { margin-bottom: 7px; }
  ol.recs .title { font-weight: bold; }
  .pagebreak { page-break-before: always; }
  #footer_content { color: #94A3B8; font-size: 7.5pt; text-align: center; }
</style>
</head>
<body>

<div id="footer_content">
  Lumina Influence AI &nbsp;·&nbsp; Relatório gerado automaticamente &nbsp;·&nbsp;
  {{ generated_at }} &nbsp;·&nbsp; Documento confidencial
</div>

<!-- ================= CAPA + SUMÁRIO ================= -->
<div class="brandbar">
  <table width="100%"><tr>
    <td class="logo">▲ Lumina Influence AI</td>
    <td align="right" class="brand">{{ campaign.brand_name }}</td>
  </tr></table>
</div>

<span class="eyebrow">Relatório de Auditoria de Performance</span>
<h1 class="cover">{{ report_title }}</h1>
<p class="desc">{{ campaign.title or campaign.brand_name }} — auditoria de performance dos criadores da campanha, com separação de alcance orgânico e pago e análise de sentimento.</p>

<table class="meta-table" width="100%">
  <tr>
    <td width="50%"><div class="meta-label">Preparado para</div>
      <div class="meta-value">{{ campaign.brand_name }}</div></td>
    <td width="50%"><div class="meta-label">Preparado por</div>
      <div class="meta-value">Lumina Influence AI</div>
      <div class="muted">{{ generated_by }}</div></td>
  </tr>
  <tr>
    <td><div class="meta-label">Período</div>
      <div class="meta-value">{{ period_start }} → {{ period_end }}</div></td>
    <td><div class="meta-label">Orçamento</div>
      <div class="meta-value">R$ {{ budget_brl }}</div></td>
  </tr>
</table>

<div class="section-wrap" style="margin-top: 14px;">
  <h2 class="section">Sumário Executivo</h2>
  {% if summary.has_data %}
  <p class="desc">Esta auditoria cobre <b>{{ summary.influencer_count }} criadores</b> da campanha
  <b>{{ campaign.brand_name }}</b>. Em média, <b>{{ summary.avg_organic_pct }}%</b> do alcance foi
  orgânico e o índice de sentimento ficou em <b>{{ summary.avg_sentiment_pct }}%</b>.
  Alcance total auditado: <b>{{ summary.total_reach_fmt }}</b> em <b>{{ summary.posts_count }}</b> posts.</p>
  {% else %}
  <p class="desc">A campanha <b>{{ campaign.brand_name }}</b> tem
  <b>{{ summary.influencer_count }} criadores</b> vinculados, mas nenhum post publicado no
  período selecionado — <b>não há dados de performance para auditar</b>. Os indicadores
  abaixo aparecem sem valor por ausência de medição, não por desempenho nulo.</p>
  {% endif %}
</div>

<!-- ================= SEÇÕES ================= -->
{% for section in sections %}
  <div class="section-wrap {% if not loop.first or true %}pagebreak{% endif %}">

  {% if section == 'kpis' %}
    <h2 class="section">KPIs da Campanha</h2>
    <table width="100%"><tr>
      {% for k in kpis %}
      <td width="25%" style="padding:3px;">
        <div class="kpi-box">
          <div class="kpi-label">{{ k.label }}</div>
          <div class="kpi-value">{% if k.depends_on_posts and not summary.has_data %}—{% else %}{{ k.value }}{% endif %}</div>
          {% if k.change is not none %}<div class="{{ 'pos' if k.change >= 0 else 'neg' }}" style="font-size:8pt;">
            {{ '+' if k.change >= 0 else '' }}{{ k.change }}%</div>{% endif %}
        </div>
      </td>
      {% endfor %}
    </tr></table>

  {% elif section == 'growth' %}
    <h2 class="section">Trajetória de Crescimento (orgânico vs pago)</h2>
    <table class="data">
      <thead><tr><th>Período</th><th class="num">Alcance Orgânico</th><th class="num">Tráfego Pago</th></tr></thead>
      <tbody>
      {% for row in growth %}
        <tr><td>{{ row.x }}</td><td class="num">{{ row.organic_fmt }}</td><td class="num">{{ row.paid_fmt }}</td></tr>
      {% else %}
        <tr><td colspan="3" class="muted">Nenhum post publicado no período.</td></tr>
      {% endfor %}
      </tbody>
    </table>

  {% elif section == 'benchmark' %}
    <h2 class="section">Benchmarking de Criadores</h2>
    <table class="data">
      <thead><tr>
        <th>Criador</th><th class="num">Alcance</th><th class="num">% Orgânico</th>
        <th class="num">Engaj.</th><th class="num">Sentim.</th><th class="num">Score IA</th>
      </tr></thead>
      <tbody>
      {% if summary.has_data %}
      {% for inf in benchmark %}
        <tr>
          <td><b>{{ inf.display_name }}</b></td>
          <td class="num">{{ inf.total_reach_fmt }}</td>
          <td class="num">{{ inf.organic_pct }}%</td>
          <td class="num">{{ inf.engagement_rate }}%</td>
          <td class="num">{{ inf.sentiment_index_pct }}%</td>
          <td class="num score">{{ inf.ai_score }}</td>
        </tr>
      {% endfor %}
      {% else %}
        <tr><td colspan="6" class="muted">Nenhum post publicado no período —
          não há dados para comparar os criadores.</td></tr>
      {% endif %}
      </tbody>
    </table>

  {% elif section == 'diagnostic' %}
    <h2 class="section">Diagnóstico de IA</h2>
    {% for d in diagnostic %}
      <div class="card">
        <table width="100%"><tr>
          <td><b>{{ d.display_name }}</b> <span class="muted">— {{ d.niche }}</span></td>
          <td align="right" class="score" style="font-size:8pt;">Bot {{ d.bot_probability }}% · Coerência {{ d.brand_coherence }}</td>
        </tr></table>
        <p class="muted" style="margin:4px 0 0 0;">{{ d.note }}</p>
      </div>
    {% endfor %}

  {% elif section == 'recommendations' %}
    <h2 class="section">Recomendações</h2>
    <ol class="recs">
      {% for r in recommendations %}
        <li><span class="title">{{ r.title }}</span><br/><span class="muted">{{ r.description }}</span></li>
      {% endfor %}
    </ol>
  {% endif %}

  </div>
{% endfor %}

</body>
</html>
"""
