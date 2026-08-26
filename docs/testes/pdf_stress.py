"""Robustez da geração de PDF — cenários que a banca apontou como quebrados.

Cada cenário roda o caminho real (build_report_context -> template -> xhtml2pdf)
e grava o PDF para conferência de texto fora daqui.
"""
import sys
import traceback
from datetime import date, timedelta

from src.app import create_app
from src.extensions import db
from src.models import Agency, Campaign, Influencer, User
from src.services import report_service

OUT = "/out"

ACENTOS = "Análise de Coerência — Ação & Reputação: “aspas”, ç, ã, õ, é, ü, ñ"
LONGO = "Relatório " + "extraordinariamente detalhado " * 12
GLIFOS = "Relatório ▲ ✓ → € 50% ½ ≤ ≥ • ®"
EMOJI = "Campanha de verão 🚀 com resultados 📈"

app = create_app()
with app.app_context():
    agency = db.session.query(Agency).first()
    user = db.session.query(User).filter_by(agency_id=agency.id).first()
    camp = db.session.query(Campaign).filter_by(agency_id=agency.id).first()
    todas = report_service.SECTION_KEYS

    hoje = date.today()
    CENARIOS = [
        ("acentuacao",        ACENTOS, hoje - timedelta(days=90), hoje, todas),
        ("titulo-no-limite",  "T" * 200, hoje - timedelta(days=90), hoje, todas),
        ("glifos-especiais",  GLIFOS,  hoje - timedelta(days=90), hoje, todas),
        ("emoji",             EMOJI,   hoje - timedelta(days=90), hoje, todas),
        ("periodo-vazio",     "Período sem posts",
                              date(2020, 1, 1), date(2020, 1, 2), todas),
        ("periodo-de-um-dia", "Um único dia", hoje, hoje, todas),
        ("periodo-longo",     "Dois anos de campanha",
                              hoje - timedelta(days=730), hoje, todas),
        ("sem-secoes",        "Relatório sem seções",
                              hoje - timedelta(days=90), hoje, []),
        ("uma-secao",         "Somente KPIs",
                              hoje - timedelta(days=90), hoje, ["kpis"]),
        ("titulo-vazio",      "", hoje - timedelta(days=90), hoje, todas),
    ]

    linhas = []
    for nome, titulo, ini, fim, secoes in CENARIOS:
        try:
            rep = report_service.generate_report(
                agency_id=agency.id, generated_by_user_id=user.id,
                generated_by_name="Marina Souza", campaign_id=camp.id,
                title=titulo, period_start=ini, period_end=fim, sections=secoes,
            )
            origem = report_service.report_pdf_path(rep)
            destino = f"{OUT}/{nome}.pdf"
            data = origem.read_bytes()
            open(destino, "wb").write(data)
            linhas.append((nome, "ok", f"{len(data)//1024} kB", ""))
            # não deixa resíduo no banco
            db.session.delete(rep)
            db.session.commit()
            origem.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            db.session.rollback()
            linhas.append((nome, f"ERRO {type(exc).__name__}", "—", str(exc)[:70]))
            traceback.print_exc(file=sys.stderr)

    # período invertido: precisa recusar, não gerar PDF torto
    try:
        report_service.generate_report(
            agency_id=agency.id, generated_by_user_id=user.id,
            generated_by_name="Marina Souza", campaign_id=camp.id,
            title="Período invertido", period_start=hoje,
            period_end=hoje - timedelta(days=30), sections=todas)
        linhas.append(("periodo-invertido", "ERRO gerou PDF", "—",
                       "deveria ter recusado"))
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        linhas.append(("periodo-invertido", "recusou", "—", type(exc).__name__))

    print("\n" + "=" * 88)
    print(f"{'CENÁRIO':22} {'RESULTADO':16} {'TAMANHO':>9}  OBSERVAÇÃO")
    print("=" * 88)
    for n, r, t, o in linhas:
        print(f"{n:22} {r:16} {t:>9}  {o}")
    print("=" * 88)
    falhas = [l for l in linhas if l[1].startswith("ERRO")]
    print(f"\n{len(linhas)} cenários · {len(linhas)-len(falhas)} ok · {len(falhas)} com falha")
