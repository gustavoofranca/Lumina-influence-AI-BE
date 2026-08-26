"""Cria a Agência B com um recurso de cada tipo, para o teste de IDOR.

Idempotente: se a agência já existe, apenas devolve os IDs.
"""
import json
from datetime import date, datetime, timedelta, timezone

from src.app import create_app
from src.extensions import db
from src.models import (Agency, Campaign, CampaignStatus, Influencer,
                        InfluencerStatus, Platform, Post, PostType, Report,
                        ReportFormat, SocialAccount, User, UserRole)

MARK = "IDOR-TEST-B"

app = create_app()
with app.app_context():
    agency = db.session.query(Agency).filter_by(name=MARK).one_or_none()
    if agency is None:
        agency = Agency(name=MARK)
        db.session.add(agency)
        db.session.flush()

        user = User(email="admin@agencia-b-idor.com.br", name="Admin B",
                    oauth_provider="google", oauth_id="idor-test-b",
                    role=UserRole.ADMIN, agency_id=agency.id)
        inf = Influencer(agency_id=agency.id, display_name="Influenciador B",
                         status=InfluencerStatus.ACTIVE)
        db.session.add_all([user, inf])
        db.session.flush()

        acc = SocialAccount(influencer_id=inf.id, platform=Platform.INSTAGRAM,
                            handle="@influenciador_b", follower_count=1000)
        camp = Campaign(agency_id=agency.id, brand_name="Marca B",
                        period_start=date.today() - timedelta(days=30),
                        period_end=date.today(), budget_brl_cents=100000,
                        status=CampaignStatus.ACTIVE)
        rep = Report(agency_id=agency.id, title="Relatorio B",
                     period_start=date.today() - timedelta(days=30),
                     period_end=date.today(), format=ReportFormat.PDF,
                     generated_at=datetime.now(timezone.utc))
        db.session.add_all([acc, camp, rep])
        db.session.flush()

        post = Post(social_account_id=acc.id, platform_post_id="idor-test-post-b",
                    post_type=PostType.REEL,
                    posted_at=datetime.now(timezone.utc) - timedelta(days=1),
                    reach_total=100, reach_organic=80, reach_paid=20,
                    impressions=120, likes=10, comments_count=2, shares=1,
                    saves=1, needs_analysis=False)
        db.session.add(post)
        db.session.commit()

    inf = db.session.query(Influencer).filter_by(agency_id=agency.id).first()
    acc = db.session.query(SocialAccount).filter_by(influencer_id=inf.id).first()
    print(json.dumps({
        "agency_id": str(agency.id),
        "user_id": str(db.session.query(User).filter_by(agency_id=agency.id).first().id),
        "influencer_id": str(inf.id),
        "social_account_id": str(acc.id),
        "post_id": str(db.session.query(Post).filter_by(social_account_id=acc.id).first().id),
        "campaign_id": str(db.session.query(Campaign).filter_by(agency_id=agency.id).first().id),
        "report_id": str(db.session.query(Report).filter_by(agency_id=agency.id).first().id),
    }))
