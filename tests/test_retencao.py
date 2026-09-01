"""Higiene de credencial e de registro técnico — o que a política promete.

Cada asserção aqui corresponde a uma frase da Política de Privacidade
publicada. Não é teste de cobertura: é o acoplamento entre um compromisso
escrito e o código que o cumpre, para que mudar um faça o outro gritar.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from sqlalchemy import func, select

from src.extensions import db
from src.jobs.cleanup_expired_tokens import run_cleanup_expired_tokens
from src.models import (
    Agency,
    ApiUsageLog,
    Influencer,
    InfluencerStatus,
    OAuthState,
    Platform,
    SocialAccount,
)
from src.models._enums import OAuthProvider
from src.utils.crypto import encrypt_token


class Base:
    pass


@pytest.fixture()
def base(app):
    """Agência descartável com contas em cada estado de token."""
    with app.app_context():
        agencia = Agency(name=f"Retenção {uuid.uuid4().hex[:6]}")
        db.session.add(agencia)
        db.session.flush()
        criador = Influencer(agency=agencia, display_name="Ret", niche="tech",
                             status=InfluencerStatus.ACTIVE)
        db.session.add(criador)
        db.session.flush()

        agora = datetime.now(timezone.utc)
        ontem = agora - timedelta(days=1)
        amanha = agora + timedelta(days=1)

        def conta(handle, *, expira, refresh):
            sa = SocialAccount(
                influencer=criador, platform=Platform.INSTAGRAM, handle=handle,
                follower_count=1, access_token_encrypted=encrypt_token("tok"),
                refresh_token_encrypted=encrypt_token("ref") if refresh else None,
                token_expires_at=expira,
            )
            db.session.add(sa)
            return sa

        c = Base()
        c.morta = conta("morta", expira=ontem, refresh=False)
        c.renovavel = conta("renovavel", expira=ontem, refresh=True)
        c.viva = conta("viva", expira=amanha, refresh=False)
        c.sem_validade = conta("semvalidade", expira=None, refresh=False)
        c.agencia_id = agencia.id
        db.session.commit()
        c.ids = {k: getattr(c, k).id for k in ("morta", "renovavel", "viva", "sem_validade")}
        yield c

        # Pelo id capturado, não pelo objeto: `_existe` desanexa a sessão, e
        # ler `agencia.id` aqui levantaria DetachedInstanceError na desmontagem.
        db.session.query(ApiUsageLog).filter(ApiUsageLog.agency_id == c.agencia_id).delete()
        alvo = db.session.get(Agency, c.agencia_id)
        if alvo is not None:
            db.session.delete(alvo)
        db.session.commit()


def _conta(base, chave):
    return db.session.get(SocialAccount, base.ids[chave])


def _existe(modelo, ident) -> bool:
    """Presença lida do banco, não da sessão.

    `db.session.get` sobre uma linha apagada por `DELETE` em massa levanta
    `ObjectDeletedError` em vez de devolver `None` — a identidade continua no
    mapa de identidade da sessão. Perguntar ao banco é o que mede o que se
    quer medir.
    """
    db.session.expunge_all()
    return db.session.scalar(
        select(func.count()).select_from(modelo).where(modelo.id == ident)
    ) > 0


# ==========================================================================
# "Tokens de acesso expirados são removidos automaticamente"
# ==========================================================================
def test_token_vencido_e_sem_renovacao_e_apagado(app, base):
    with app.app_context():
        assert run_cleanup_expired_tokens()["dead_tokens_purged"] >= 1
    db.session.expire_all()
    morta = _conta(base, "morta")
    assert morta.access_token_encrypted is None
    assert morta.token_expires_at is None
    # A conta sobrevive: ela registra o vínculo, e apagá-la levaria os posts.
    assert morta is not None


def test_token_vencido_mas_renovavel_nao_e_tocado(app, base):
    # Ali o vencimento é rotina — apagar quebraria uma conexão que funciona.
    with app.app_context():
        run_cleanup_expired_tokens()
    db.session.expire_all()
    assert _conta(base, "renovavel").access_token_encrypted is not None


def test_token_dentro_da_validade_nao_e_tocado(app, base):
    with app.app_context():
        run_cleanup_expired_tokens()
    db.session.expire_all()
    assert _conta(base, "viva").access_token_encrypted is not None


def test_token_sem_data_de_validade_nao_e_tocado(app, base):
    # Sem `token_expires_at` não há como afirmar que venceu, e apagar por
    # suposição desligaria a coleta de uma conta que talvez esteja boa.
    with app.app_context():
        run_cleanup_expired_tokens()
    db.session.expire_all()
    assert _conta(base, "sem_validade").access_token_encrypted is not None


# ==========================================================================
# "Registros técnicos são descartados em até 90 dias"
# ==========================================================================
def test_registro_de_uso_fora_da_janela_e_descartado(app, base):
    agora = datetime.now(timezone.utc)
    velho = ApiUsageLog(agency_id=base.agencia_id, endpoint="POST /x", tokens_used=10,
                        called_at=agora - timedelta(days=120))
    recente = ApiUsageLog(agency_id=base.agencia_id, endpoint="POST /y", tokens_used=10,
                          called_at=agora - timedelta(days=10))
    db.session.add_all([velho, recente])
    db.session.commit()
    # Os ids saem antes do job: depois do commit dele o objeto está expirado, e
    # ler `.id` dispara um refresh que estoura numa linha já apagada.
    id_velho, id_recente = velho.id, recente.id

    with app.app_context():
        resultado = run_cleanup_expired_tokens()
    assert resultado["usage_logs_purged"] >= 1
    assert resultado["retention_days"] == 90

    assert not _existe(ApiUsageLog, id_velho)
    assert _existe(ApiUsageLog, id_recente)


def test_a_janela_de_retencao_vem_da_configuracao(app, base, monkeypatch):
    # O número está escrito na política publicada; deixá-lo em literal no meio
    # do job esconderia a mudança de um compromisso dentro de um refactor.
    agora = datetime.now(timezone.utc)
    registro = ApiUsageLog(agency_id=base.agencia_id, endpoint="POST /z", tokens_used=1,
                           called_at=agora - timedelta(days=20))
    db.session.add(registro)
    db.session.commit()
    id_registro = registro.id

    with app.app_context():
        monkeypatch.setitem(app.config, "RETENTION_DAYS", 7)
        resultado = run_cleanup_expired_tokens()
    assert resultado["retention_days"] == 7
    assert not _existe(ApiUsageLog, id_registro)


# ==========================================================================
# O que já existia continua valendo
# ==========================================================================
def test_state_oauth_expirado_continua_sendo_removido(app, base):
    expirado = OAuthState(
        state_token=f"exp-{uuid.uuid4().hex}", provider=OAuthProvider.GOOGLE,
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    vivo = OAuthState(
        state_token=f"viv-{uuid.uuid4().hex}", provider=OAuthProvider.GOOGLE,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.session.add_all([expirado, vivo])
    db.session.commit()
    id_expirado, id_vivo = expirado.id, vivo.id

    with app.app_context():
        run_cleanup_expired_tokens()
    assert not _existe(OAuthState, id_expirado)
    assert _existe(OAuthState, id_vivo)


def test_o_job_e_idempotente(app, base):
    # Roda todo dia: a segunda passagem não pode achar nada novo para apagar.
    with app.app_context():
        primeira = run_cleanup_expired_tokens()
        segunda = run_cleanup_expired_tokens()
    assert primeira["dead_tokens_purged"] >= 1
    assert segunda["dead_tokens_purged"] == 0
