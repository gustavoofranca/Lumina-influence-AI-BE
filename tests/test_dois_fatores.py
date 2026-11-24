"""2FA por app autenticador — spec de 19/10/2026.

A conta de teste (`conta_com_senha`) é administradora, e administrador sem 2FA
não recebe sessão no login: recebe o ticket de ativação. Os testes de membro
trocam o papel da conta antes de entrar.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from src.extensions import db
from src.models import AuthToken, CodigoRecuperacao, FinalidadeToken, User, UserRole
from src.utils import totp
from src.utils.crypto import decrypt_token
from src.utils.jwt_utils import encode_token, issue_token_pair

LOGIN, ME = "/api/v1/auth/login", "/api/v1/auth/me"
VERIFY, SETUP = "/api/v1/auth/2fa/verify", "/api/v1/auth/2fa/setup"
CONFIRM, DISABLE = "/api/v1/auth/2fa/setup/confirm", "/api/v1/auth/2fa/disable"
RECOVERY = "/api/v1/auth/2fa/recovery-codes"
FORMATO_DE_RECUPERACAO = re.compile(r"^[a-z2-9]{4}-[a-z2-9]{4}$")


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _entrar(client, conta):
    return client.post(LOGIN, json={"email": conta.email, "password": conta.senha})


def _mudar(app, conta, **campos):
    with app.app_context():
        user = db.session.get(User, conta.id)
        for nome, valor in campos.items():
            setattr(user, nome, valor)
        db.session.commit()


def _sessao(app, conta) -> str:
    with app.app_context():
        return issue_token_pair(db.session.get(User, conta.id))["access_token"]


def _codigo_agora(segredo: str) -> str:
    return totp.codigo(segredo, totp.passo_atual())


def _ativar_pelo_login(client, conta) -> tuple[str, list[str], dict]:
    """Admin entra, ativa com o ticket e devolve (segredo, códigos, sessão)."""
    ticket = _entrar(client, conta).get_json()["data"]["mfa_ticket"]
    segredo = client.post(SETUP, json={"mfa_ticket": ticket}).get_json()["data"]["secret"]
    r = client.post(CONFIRM, json={"mfa_ticket": ticket, "code": _codigo_agora(segredo)})
    assert r.status_code == 200, r.get_json()
    dados = r.get_json()["data"]
    return segredo, dados["recovery_codes"], dados


def _proximo_codigo(segredo: str) -> str:
    """Código de outro passo da janela: o atual já foi gasto na ativação."""
    return totp.codigo(segredo, totp.passo_atual() + 1)


@pytest.fixture()
def membro(app, conta_com_senha):
    _mudar(app, conta_com_senha, role=UserRole.MEMBER)
    return conta_com_senha


# ---------------------------------------------------------------- obrigatoriedade
def test_admin_sem_2fa_recebe_ticket_de_ativacao_e_nao_a_sessao(client, conta_com_senha):
    r = _entrar(client, conta_com_senha)
    assert r.status_code == 200
    dados = r.get_json()["data"]
    assert dados["mfa"] == "setup"
    assert dados["mfa_ticket"]
    assert "tokens" not in dados


def test_membro_sem_2fa_entra_direto(client, membro):
    dados = _entrar(client, membro).get_json()["data"]
    assert "mfa" not in dados
    assert dados["tokens"]["access_token"]


def test_ticket_de_ativacao_nao_abre_rota_autenticada(client, conta_com_senha):
    ticket = _entrar(client, conta_com_senha).get_json()["data"]["mfa_ticket"]
    assert client.get(ME, headers=_h(ticket)).status_code == 401


def test_admin_obrigatorio_pode_ser_desligado_por_configuracao(client, app, conta_com_senha, monkeypatch):
    monkeypatch.setitem(app.config, "MFA_OBRIGATORIO_PARA_ADMIN", False)
    assert "tokens" in _entrar(client, conta_com_senha).get_json()["data"]


# ---------------------------------------------------------------- ativação
def test_ativacao_pelo_ticket(client, app, conta_com_senha, outbox):
    ticket = _entrar(client, conta_com_senha).get_json()["data"]["mfa_ticket"]
    r = client.post(SETUP, json={"mfa_ticket": ticket})
    assert r.status_code == 200
    inicio = r.get_json()["data"]
    assert inicio["otpauth_uri"].startswith("otpauth://totp/Lumina:")
    assert inicio["qr_svg"].startswith("data:image/svg+xml")

    r = client.post(CONFIRM, json={"mfa_ticket": ticket, "code": _codigo_agora(inicio["secret"])})
    assert r.status_code == 200
    dados = r.get_json()["data"]
    assert len(dados["recovery_codes"]) == 10
    assert len(set(dados["recovery_codes"])) == 10
    assert all(FORMATO_DE_RECUPERACAO.match(c) for c in dados["recovery_codes"])
    assert dados["user"]["mfa_enabled"] is True
    assert dados["user"]["recovery_codes_left"] == 10
    assert client.get(ME, headers=_h(dados["tokens"]["access_token"])).status_code == 200
    assert any("2FA" in m.assunto for m in outbox)

    # O ticket gastou-se na confirmação.
    assert client.post(CONFIRM, json={"mfa_ticket": ticket, "code": "123456"}).status_code == 400


def test_segredo_fica_cifrado_no_banco(client, app, conta_com_senha):
    segredo, _, _ = _ativar_pelo_login(client, conta_com_senha)
    with app.app_context():
        user = db.session.get(User, conta_com_senha.id)
        assert user.totp_segredo_cifrado != segredo
        assert decrypt_token(user.totp_segredo_cifrado) == segredo


def test_codigos_de_recuperacao_nao_ficam_em_claro(client, app, conta_com_senha):
    _, codigos, _ = _ativar_pelo_login(client, conta_com_senha)
    with app.app_context():
        gravados = db.session.scalars(
            select(CodigoRecuperacao.codigo_hash).where(CodigoRecuperacao.user_id == conta_com_senha.id)
        ).all()
    assert len(gravados) == 10
    assert not set(gravados) & {c.replace("-", "") for c in codigos} & set(codigos)
    assert all(len(h) == 64 for h in gravados)


def test_confirmacao_com_codigo_errado_nao_ativa(client, app, conta_com_senha):
    ticket = _entrar(client, conta_com_senha).get_json()["data"]["mfa_ticket"]
    client.post(SETUP, json={"mfa_ticket": ticket})
    r = client.post(CONFIRM, json={"mfa_ticket": ticket, "code": "000000"})
    assert r.status_code == 422
    assert r.get_json()["error"]["details"]["fields"][0]["field"] == "code"
    with app.app_context():
        assert db.session.get(User, conta_com_senha.id).totp_ativado_em is None


def test_confirmar_sem_iniciar_e_recusado(client, conta_com_senha):
    ticket = _entrar(client, conta_com_senha).get_json()["data"]["mfa_ticket"]
    assert client.post(CONFIRM, json={"mfa_ticket": ticket, "code": "123456"}).status_code == 409


def test_membro_ativa_pela_sessao_e_as_outras_sessoes_caem(client, app, membro):
    antiga = encode_token(token_type="access", user_id=membro.id, extra={"iat": int(time.time()) - 60})
    atual = _sessao(app, membro)
    segredo = client.post(SETUP, json={}, headers=_h(atual)).get_json()["data"]["secret"]
    r = client.post(CONFIRM, json={"code": _codigo_agora(segredo)}, headers=_h(atual))
    assert r.status_code == 200
    nova = r.get_json()["data"]["tokens"]["access_token"]
    assert client.get(ME, headers=_h(nova)).status_code == 200
    assert client.get(ME, headers=_h(antiga)).get_json()["error"]["code"] == "token_revoked"


def test_ativar_de_novo_com_2fa_ligado_e_conflito(client, app, conta_com_senha):
    _, _, dados = _ativar_pelo_login(client, conta_com_senha)
    r = client.post(SETUP, json={}, headers=_h(dados["tokens"]["access_token"]))
    assert r.status_code == 409


def test_setup_sem_ticket_nem_sessao_e_401(client):
    assert client.post(SETUP, json={}).status_code == 401


# ---------------------------------------------------------------- desafio
def test_com_2fa_o_login_pede_o_codigo(client, conta_com_senha):
    _ativar_pelo_login(client, conta_com_senha)
    dados = _entrar(client, conta_com_senha).get_json()["data"]
    assert dados["mfa"] == "challenge" and dados["mfa_ticket"] and "tokens" not in dados


def test_codigo_do_app_libera_a_sessao(client, conta_com_senha):
    segredo, _, _ = _ativar_pelo_login(client, conta_com_senha)
    ticket = _entrar(client, conta_com_senha).get_json()["data"]["mfa_ticket"]
    r = client.post(VERIFY, json={"mfa_ticket": ticket, "code": _proximo_codigo(segredo)})
    assert r.status_code == 200
    assert client.get(ME, headers=_h(r.get_json()["data"]["tokens"]["access_token"])).status_code == 200


def test_mesmo_codigo_nao_vale_duas_vezes(client, conta_com_senha):
    segredo, _, _ = _ativar_pelo_login(client, conta_com_senha)
    codigo = _proximo_codigo(segredo)
    ticket = _entrar(client, conta_com_senha).get_json()["data"]["mfa_ticket"]
    assert client.post(VERIFY, json={"mfa_ticket": ticket, "code": codigo}).status_code == 200
    ticket = _entrar(client, conta_com_senha).get_json()["data"]["mfa_ticket"]
    assert client.post(VERIFY, json={"mfa_ticket": ticket, "code": codigo}).status_code == 422


def test_codigo_anterior_ao_ultimo_aceito_e_recusado(client, conta_com_senha):
    """Replay de um passo mais antigo, ainda dentro da janela."""
    segredo, _, _ = _ativar_pelo_login(client, conta_com_senha)
    ticket = _entrar(client, conta_com_senha).get_json()["data"]["mfa_ticket"]
    passo = totp.passo_atual()
    assert client.post(VERIFY, json={"mfa_ticket": ticket, "code": totp.codigo(segredo, passo + 1)}).status_code == 200
    ticket = _entrar(client, conta_com_senha).get_json()["data"]["mfa_ticket"]
    r = client.post(VERIFY, json={"mfa_ticket": ticket, "code": totp.codigo(segredo, passo - 1)})
    assert r.status_code == 422


def test_codigo_fora_da_janela_e_recusado(client, conta_com_senha):
    segredo, _, _ = _ativar_pelo_login(client, conta_com_senha)
    ticket = _entrar(client, conta_com_senha).get_json()["data"]["mfa_ticket"]
    velho = totp.codigo(segredo, totp.passo_atual() - 5)
    janela = {totp.codigo(segredo, totp.passo_atual() + d) for d in (-1, 0, 1)}
    if velho not in janela:
        assert client.post(VERIFY, json={"mfa_ticket": ticket, "code": velho}).status_code == 422


def test_limite_de_tentativas_no_codigo(client, conta_com_senha):
    segredo, _, _ = _ativar_pelo_login(client, conta_com_senha)
    ticket = _entrar(client, conta_com_senha).get_json()["data"]["mfa_ticket"]
    for _ in range(5):
        assert client.post(VERIFY, json={"mfa_ticket": ticket, "code": "000000"}).status_code == 422
    # Até o código certo é barrado enquanto o limite vale.
    r = client.post(VERIFY, json={"mfa_ticket": ticket, "code": _proximo_codigo(segredo)})
    assert r.status_code == 429


def test_falha_no_codigo_nao_gasta_o_ticket(client, conta_com_senha):
    segredo, _, _ = _ativar_pelo_login(client, conta_com_senha)
    ticket = _entrar(client, conta_com_senha).get_json()["data"]["mfa_ticket"]
    assert client.post(VERIFY, json={"mfa_ticket": ticket, "code": "000000"}).status_code == 422
    assert client.post(VERIFY, json={"mfa_ticket": ticket, "code": _proximo_codigo(segredo)}).status_code == 200


def test_ticket_usado_nao_vale_de_novo(client, conta_com_senha):
    segredo, _, _ = _ativar_pelo_login(client, conta_com_senha)
    ticket = _entrar(client, conta_com_senha).get_json()["data"]["mfa_ticket"]
    assert client.post(VERIFY, json={"mfa_ticket": ticket, "code": _proximo_codigo(segredo)}).status_code == 200
    r = client.post(VERIFY, json={"mfa_ticket": ticket, "code": _proximo_codigo(segredo)})
    assert r.status_code == 400
    assert r.get_json()["error"]["code"] == "mfa_ticket_invalid"


def test_ticket_vencido(client, app, conta_com_senha):
    segredo, _, _ = _ativar_pelo_login(client, conta_com_senha)
    ticket = _entrar(client, conta_com_senha).get_json()["data"]["mfa_ticket"]
    with app.app_context():
        for registro in db.session.scalars(select(AuthToken).where(
            AuthToken.user_id == conta_com_senha.id, AuthToken.finalidade == FinalidadeToken.DESAFIO_2FA,
        )):
            registro.expira_em = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.session.commit()
    r = client.post(VERIFY, json={"mfa_ticket": ticket, "code": _proximo_codigo(segredo)})
    assert r.status_code == 400
    assert r.get_json()["error"]["code"] == "mfa_ticket_expired"


def test_ticket_de_ativacao_nao_serve_no_desafio(client, conta_com_senha):
    ticket = _entrar(client, conta_com_senha).get_json()["data"]["mfa_ticket"]
    r = client.post(VERIFY, json={"mfa_ticket": ticket, "code": "123456"})
    assert r.status_code == 400
    assert r.get_json()["error"]["code"] == "mfa_ticket_invalid"


def test_novo_login_invalida_o_ticket_anterior(client, conta_com_senha):
    segredo, _, _ = _ativar_pelo_login(client, conta_com_senha)
    primeiro = _entrar(client, conta_com_senha).get_json()["data"]["mfa_ticket"]
    _entrar(client, conta_com_senha)
    assert client.post(VERIFY, json={"mfa_ticket": primeiro, "code": _proximo_codigo(segredo)}).status_code == 400


# ---------------------------------------------------------------- recuperação
def test_codigo_de_recuperacao_entra_uma_vez_e_avisa(client, conta_com_senha, outbox):
    _, codigos, _ = _ativar_pelo_login(client, conta_com_senha)
    outbox.clear()
    ticket = _entrar(client, conta_com_senha).get_json()["data"]["mfa_ticket"]
    # Aceita maiúsculas, sem hífen e com espaços: é digitado de um papel.
    digitado = "  " + codigos[0].replace("-", "").upper() + " "
    r = client.post(VERIFY, json={"mfa_ticket": ticket, "code": digitado})
    assert r.status_code == 200
    assert r.get_json()["data"]["user"]["recovery_codes_left"] == 9
    assert any("recuperação" in m.assunto for m in outbox)

    ticket = _entrar(client, conta_com_senha).get_json()["data"]["mfa_ticket"]
    assert client.post(VERIFY, json={"mfa_ticket": ticket, "code": codigos[0]}).status_code == 422


def test_novos_codigos_invalidam_os_anteriores(client, conta_com_senha):
    segredo, antigos, dados = _ativar_pelo_login(client, conta_com_senha)
    r = client.post(RECOVERY, json={"code": _proximo_codigo(segredo)},
                    headers=_h(dados["tokens"]["access_token"]))
    assert r.status_code == 200
    novos = r.get_json()["data"]["recovery_codes"]
    assert len(novos) == 10 and not set(novos) & set(antigos)
    ticket = _entrar(client, conta_com_senha).get_json()["data"]["mfa_ticket"]
    assert client.post(VERIFY, json={"mfa_ticket": ticket, "code": antigos[1]}).status_code == 422
    assert client.post(VERIFY, json={"mfa_ticket": ticket, "code": novos[0]}).status_code == 200


def test_novos_codigos_exigem_codigo_valido(client, conta_com_senha):
    _, _, dados = _ativar_pelo_login(client, conta_com_senha)
    r = client.post(RECOVERY, json={"code": "000000"}, headers=_h(dados["tokens"]["access_token"]))
    assert r.status_code == 422


# ---------------------------------------------------------------- desligar
def test_admin_nao_pode_desligar(client, conta_com_senha):
    segredo, _, dados = _ativar_pelo_login(client, conta_com_senha)
    r = client.post(DISABLE, json={"code": _proximo_codigo(segredo), "password": conta_com_senha.senha},
                    headers=_h(dados["tokens"]["access_token"]))
    assert r.status_code == 403
    assert r.get_json()["error"]["code"] == "mfa_required_for_admin"


def test_membro_desliga_com_senha_e_codigo(client, app, membro, outbox):
    atual = _sessao(app, membro)
    segredo = client.post(SETUP, json={}, headers=_h(atual)).get_json()["data"]["secret"]
    sessao = client.post(CONFIRM, json={"code": _codigo_agora(segredo)},
                         headers=_h(atual)).get_json()["data"]["tokens"]["access_token"]
    outbox.clear()

    sem_senha = client.post(DISABLE, json={"code": _proximo_codigo(segredo)}, headers=_h(sessao))
    assert sem_senha.status_code == 422
    assert sem_senha.get_json()["error"]["details"]["fields"][0]["field"] == "password"
    errada = client.post(DISABLE, json={"code": _proximo_codigo(segredo), "password": "senha errada mesmo"},
                         headers=_h(sessao))
    assert errada.status_code == 422

    r = client.post(DISABLE, json={"code": _proximo_codigo(segredo), "password": membro.senha},
                    headers=_h(sessao))
    assert r.status_code == 204
    with app.app_context():
        user = db.session.get(User, membro.id)
        assert user.totp_ativado_em is None and user.totp_segredo_cifrado is None
        assert user.recovery_codes_left == 0
    assert any("2FA" in m.assunto for m in outbox)
    assert "tokens" in _entrar(client, membro).get_json()["data"]


# ---------------------------------------------------------------- troca de senha
def test_trocar_senha_com_2fa_pede_o_codigo(client, conta_com_senha):
    segredo, _, dados = _ativar_pelo_login(client, conta_com_senha)
    h = _h(dados["tokens"]["access_token"])
    corpo = {"current_password": conta_com_senha.senha, "new_password": "outra senha bem comprida"}
    r = client.post("/api/v1/auth/change-password", json=corpo, headers=h)
    assert r.status_code == 422
    assert r.get_json()["error"]["details"]["fields"][0]["field"] == "totp_code"
    r = client.post("/api/v1/auth/change-password",
                    json={**corpo, "totp_code": _proximo_codigo(segredo)}, headers=h)
    assert r.status_code == 200
    assert r.get_json()["data"]["tokens"]["access_token"]


# ---------------------------------------------------------------- OAuth e atalho de dev
def test_callback_do_google_leva_o_ticket_no_fragmento(client, app, monkeypatch):
    from src.integrations.base_oauth import OAuthUserInfo
    from src.integrations.google_oauth import GoogleOAuthClient

    monkeypatch.setattr(GoogleOAuthClient, "exchange_code",
                        lambda self, *, code, redirect_uri: {"access_token": "x"})
    monkeypatch.setattr(GoogleOAuthClient, "fetch_user_info", lambda self, t: OAuthUserInfo(
        provider="google", oauth_id="g-2fa", email="dono-novo@agencia.com.br", name="Dono Novo",
        avatar_url=None))
    monkeypatch.setitem(app.config, "AUTH_SUCCESS_REDIRECT", "http://localhost:5173/auth/callback")
    try:
        state = parse_qs(urlparse(client.get("/api/v1/auth/google/login").headers["Location"]).query)["state"][0]
        r = client.get(f"/api/v1/auth/google/callback?code=c&state={state}")
        fragmento = parse_qs(urlparse(r.headers["Location"]).fragment)
        # Conta nova pelo Google é admin da agência nova: vai para a ativação.
        assert fragmento["mfa"] == ["setup"]
        assert fragmento["mfa_ticket"][0]
        assert "access_token" not in fragmento
        assert fragmento["new_agency"] == ["1"]
    finally:
        with app.app_context():
            user = db.session.scalar(select(User).where(User.email == "dono-novo@agencia.com.br"))
            if user is not None:
                db.session.delete(user.agency)
                db.session.commit()


def test_atalho_de_dev_nao_pede_2fa(client, app, conta_com_senha, monkeypatch):
    monkeypatch.setitem(app.config, "DEV_LOGIN_ENABLED", True)
    r = client.post("/api/v1/auth/dev-login", json={"email": conta_com_senha.email})
    assert r.status_code == 200
    assert r.get_json()["data"]["tokens"]["access_token"]


# ---------------------------------------------------------------- último recurso
def test_comando_reset_2fa(client, app, conta_com_senha, outbox):
    _ativar_pelo_login(client, conta_com_senha)
    outbox.clear()
    resultado = app.test_cli_runner().invoke(args=["users", "reset-2fa", conta_com_senha.email])
    assert resultado.exit_code == 0, resultado.output
    assert "[OK]" in resultado.output
    with app.app_context():
        user = db.session.get(User, conta_com_senha.id)
        assert user.totp_ativado_em is None and user.recovery_codes_left == 0
    assert any("2FA" in m.assunto for m in outbox)
    # Admin volta a ser levado à ativação no próximo login.
    assert _entrar(client, conta_com_senha).get_json()["data"]["mfa"] == "setup"


def test_comando_reset_2fa_com_email_desconhecido(app):
    resultado = app.test_cli_runner().invoke(args=["users", "reset-2fa", "ninguem@agencia.com.br"])
    assert resultado.exit_code == 1
    assert "[ERRO]" in resultado.output
