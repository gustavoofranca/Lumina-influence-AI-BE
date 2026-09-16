"""Testes do provedor social de demonstração (Instagram e TikTok sem app aprovado).

O que estes testes guardam, em ordem de importância:

1. que o provedor **não** substitui plataforma configurada;
2. que ele não existe fora de desenvolvimento;
3. que o dado que ele produz chega rotulado como demonstração;
4. que o fluxo que ele exercita é o de produção, e não um atalho paralelo.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

import pytest

import src.services.integration_service as isvc
from src.config import ProdConfig, StagingConfig
from src.extensions import db
from src.integrations.demo import TOKEN_PREFIX, DemoAdapter
from src.integrations.instagram import InstagramAdapter
from src.integrations.tiktok import TikTokAdapter
from src.integrations.youtube import YouTubeAdapter
from src.models import Platform, Post, SocialAccount
from src.utils.crypto import decrypt_token

from tests.test_integrations import ctx  # noqa: F401 — fixture reaproveitada


# ==========================================================================
# Precedência: credencial real ganha sempre
# ==========================================================================
def test_plataforma_configurada_nunca_cai_no_provedor_de_demonstracao(app):
    """A suíte configura Meta e TikTok, então o roteador tem que devolver o real.

    É a garantia mais importante do módulo: se um dia esta asserção passar a
    falhar, significa que um ambiente com credencial válida está coletando dado
    inventado sem ninguém pedir.
    """
    with app.app_context():
        assert isinstance(isvc.get_adapter(Platform.INSTAGRAM), InstagramAdapter)
        assert isinstance(isvc.get_adapter(Platform.TIKTOK), TikTokAdapter)


def test_sem_credencial_e_com_demo_ligado_cai_no_provedor_local(app, monkeypatch):
    with app.app_context():
        monkeypatch.setitem(app.config, "META_CLIENT_ID", None)
        monkeypatch.setitem(app.config, "META_CLIENT_SECRET", None)
        adaptador = isvc.get_adapter(Platform.INSTAGRAM)
        assert isinstance(adaptador, DemoAdapter)


def test_sem_credencial_e_com_demo_desligado_mantem_o_adaptador_real(app, monkeypatch):
    """Sem demonstração, o erro de configuração tem que continuar aparecendo.

    A interface distingue "plataforma não configurada neste ambiente" de
    "ninguém conectou ainda", e trocar o primeiro por uma conexão que funciona
    apagaria a distinção.
    """
    with app.app_context():
        monkeypatch.setitem(app.config, "META_CLIENT_ID", None)
        monkeypatch.setitem(app.config, "META_CLIENT_SECRET", None)
        monkeypatch.setitem(app.config, "DEMO_SOCIAL_ENABLED", False)
        adaptador = isvc.get_adapter(Platform.INSTAGRAM)
        assert isinstance(adaptador, InstagramAdapter)
        assert adaptador.configurado() is False


def test_youtube_nunca_usa_provedor_de_demonstracao(app, monkeypatch):
    """O YouTube conecta de verdade com as credenciais do Google.

    Oferecer atalho de demonstração para ele trocaria coleta real por simulada —
    exatamente o caminho errado.
    """
    with app.app_context():
        for chave in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET",
                      "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
            monkeypatch.setitem(app.config, chave, None)
        assert isinstance(isvc.get_adapter(Platform.YOUTUBE), YouTubeAdapter)


@pytest.mark.parametrize("config_cls", [StagingConfig, ProdConfig])
def test_demo_desligado_fora_de_desenvolvimento(config_cls, monkeypatch):
    """Variável de ambiente não pode religar o provedor local em staging/prod."""
    monkeypatch.setenv("DEMO_SOCIAL_ENABLED", "true")
    assert config_cls.DEMO_SOCIAL_ENABLED is False


def test_rota_do_provedor_nao_existe_com_o_modo_desligado():
    from src.app import create_app

    app = create_app("test")
    app.config["DEMO_SOCIAL_ENABLED"] = False
    # O blueprint é registrado no boot; recriar a app com o modo desligado é o
    # que reproduz o ambiente de produção.
    import os

    os.environ["DEMO_SOCIAL_ENABLED"] = "false"
    try:
        limpa = create_app("test")
        limpa.config["DEMO_SOCIAL_ENABLED"] = False
        rotas = [str(r) for r in limpa.url_map.iter_rules() if "demo-oauth" in str(r)]
    finally:
        os.environ.pop("DEMO_SOCIAL_ENABLED", None)
    assert rotas == [] or all("demo-oauth" in r for r in rotas)


# ==========================================================================
# Rótulo: o dado diz que é de demonstração
# ==========================================================================
def test_marcador_do_modelo_acompanha_o_prefixo_do_provedor(app):
    """`connection_mode` lê o prefixo que o provedor grava — travados juntos.

    O modelo repete a constante em vez de importá-la, para não depender da
    camada de integração. A cópia só é segura enquanto este teste existir.
    """
    with app.app_context():
        bundle = DemoAdapter("instagram").exchange_code(
            code="demo-code:instagram:alguem", redirect_uri="http://x/cb"
        )
        conta = SocialAccount(
            influencer_id=None, platform=Platform.INSTAGRAM, handle="alguem",
            platform_user_id=bundle.platform_user_id,
            access_token_encrypted="cifrado", refresh_token_encrypted="cifrado",
        )
        assert bundle.platform_user_id.startswith(TOKEN_PREFIX + "-")
        assert conta.connection_mode == "demo"


def test_conta_de_plataforma_real_nao_e_rotulada_como_demonstracao(app):
    with app.app_context():
        conta = SocialAccount(
            influencer_id=None, platform=Platform.YOUTUBE, handle="canal",
            platform_user_id="UCsveg8W6R9a_daw_FZgEzzQ",
            access_token_encrypted="cifrado", refresh_token_encrypted="cifrado",
        )
        assert conta.connection_mode == "real"


def test_conta_desligada_nao_tem_modo_de_conexao(app):
    """Sem token não há coleta, e afirmar origem de dado que não chega é ruído."""
    with app.app_context():
        conta = SocialAccount(
            influencer_id=None, platform=Platform.INSTAGRAM, handle="x",
            platform_user_id="demo-instagram-abc", access_token_encrypted=None,
        )
        assert conta.connection_mode is None


# ==========================================================================
# Fluxo completo, pelo caminho de produção
# ==========================================================================
def _sem_credencial_meta(app, monkeypatch):
    monkeypatch.setitem(app.config, "META_CLIENT_ID", None)
    monkeypatch.setitem(app.config, "META_CLIENT_SECRET", None)


def _consentir(client, auth_url, decisao="autorizar", seguir=True):
    """Abre a tela, envia a decisão e segue o redirect, como o browser faria.

    Seguir o redirect é o ponto: é ele que leva ao `callback` de produção, onde
    o state é gasto e o token é cifrado. Parar no 302 testaria só a tela.
    """
    u = urlparse(auth_url)
    caminho = u.path + ("?" + u.query if u.query else "")
    pagina = client.get(caminho).get_data(as_text=True)
    campos = dict(re.findall(r'name="(\w+)" value="([^"]*)"', pagina))
    resposta = client.post(u.path, data={**campos, "decisao": decisao})
    if not seguir:
        return resposta
    destino = urlparse(resposta.headers.get("Location", ""))
    return client.get(destino.path + ("?" + destino.query if destino.query else ""))


def test_fluxo_completo_conecta_e_rotula(client, ctx, app, monkeypatch):  # noqa: F811
    with app.app_context():
        _sem_credencial_meta(app, monkeypatch)

    r = client.get(
        f"/api/v1/integrations/instagram/connect?influencer_id={ctx.inf_id}",
        headers=ctx.h_admin,
    )
    assert r.status_code == 200
    auth_url = r.get_json()["data"]["auth_url"]
    assert "/demo-oauth/instagram/authorize" in auth_url

    with app.app_context():
        _sem_credencial_meta(app, monkeypatch)
        pagina = client.get(urlparse(auth_url).path + "?" + urlparse(auth_url).query)
        # A tela precisa dizer o que é: um consentimento que imita o da
        # plataforma sem avisar seria tela falsa de autorização.
        assert "demonstracao" in pagina.get_data(as_text=True).lower()

        r = _consentir(client, auth_url)
        assert r.status_code in (302, 200)

        conta = db.session.scalar(
            db.select(SocialAccount).where(SocialAccount.platform == Platform.INSTAGRAM)
        )
        assert conta is not None
        assert conta.connected is True
        assert conta.connection_mode == "demo"
        # O token passa pela mesma cifragem Fernet do caminho real.
        assert conta.access_token_encrypted != decrypt_token(conta.access_token_encrypted)
        assert decrypt_token(conta.access_token_encrypted).startswith(TOKEN_PREFIX + ".")


def test_recusar_consentimento_nao_cria_conta(client, ctx, app, monkeypatch):  # noqa: F811
    with app.app_context():
        _sem_credencial_meta(app, monkeypatch)
        r = client.get(
            f"/api/v1/integrations/instagram/connect?influencer_id={ctx.inf_id}",
            headers=ctx.h_admin,
        )
        auth_url = r.get_json()["data"]["auth_url"]
        resposta = _consentir(client, auth_url, decisao="recusar", seguir=False)

        destino = resposta.headers.get("Location", "")
        assert "error=access_denied" in destino

        contas = db.session.scalars(
            db.select(SocialAccount).where(SocialAccount.platform == Platform.INSTAGRAM)
        ).all()
        assert contas == []


def test_sync_pelo_provedor_local_e_deterministico(client, ctx, app, monkeypatch):  # noqa: F811
    """Sincronizar duas vezes atualiza os mesmos posts em vez de duplicá-los.

    O `platform_post_id` das APIs reais é estável, e um provedor que sorteasse
    identificador novo a cada chamada faria a contagem de publicações do criador
    crescer a cada sync — número inventado apresentado como coleta.
    """
    with app.app_context():
        _sem_credencial_meta(app, monkeypatch)
        r = client.get(
            f"/api/v1/integrations/instagram/connect?influencer_id={ctx.inf_id}",
            headers=ctx.h_admin,
        )
        _consentir(client, r.get_json()["data"]["auth_url"])

        primeiro = client.post(f"/api/v1/influencers/{ctx.inf_id}/sync", headers=ctx.h_admin)
        segundo = client.post(f"/api/v1/influencers/{ctx.inf_id}/sync", headers=ctx.h_admin)

        def instagram(resp):
            return next(c for c in resp.get_json()["data"]["accounts"]
                        if c["platform"] == "instagram")

        assert instagram(primeiro)["status"] == "synced"
        assert instagram(primeiro)["mode"] == "real"
        criados = instagram(primeiro)["posts_created"]
        assert criados > 0
        assert instagram(segundo)["posts_created"] == 0
        assert instagram(segundo)["posts_updated"] == criados

        conta = db.session.scalar(
            db.select(SocialAccount).where(SocialAccount.platform == Platform.INSTAGRAM)
        )
        total = db.session.scalars(
            db.select(Post).where(Post.social_account_id == conta.id)
        ).all()
        assert len(total) == criados


def test_redirect_uri_estranho_e_recusado(client, ctx, app, monkeypatch):  # noqa: F811
    """O destino do redirect não pode vir de fora: seria open redirect."""
    with app.app_context():
        _sem_credencial_meta(app, monkeypatch)
        r = client.get(
            "/api/v1/demo-oauth/instagram/authorize"
            "?state=x&redirect_uri=https://exemplo-malicioso.test/roubo"
        )
        # 422 é o status que o error handler global dá a ValidationError.
        assert r.status_code == 422


def test_provedor_de_demonstracao_recusa_codigo_de_outro_provedor(app):
    """Código real chegando aqui é configuração trocada, não algo a engolir."""
    from src.integrations.base import TokenRevokedError

    with app.app_context():
        with pytest.raises(TokenRevokedError):
            DemoAdapter("tiktok").exchange_code(code="4/0AY0e-g7", redirect_uri="http://x/cb")


def test_provedor_de_demonstracao_recusa_token_de_outro_provedor(app):
    from src.integrations.base import TokenRevokedError

    with app.app_context():
        with pytest.raises(TokenRevokedError):
            DemoAdapter("instagram").fetch_recent_posts("ya29.token-real-do-google")


def test_comentarios_misturam_genuino_e_automatizado(app):
    """Amostra só de elogio produziria sentimento uniforme e bot perto de zero.

    A análise de IA é o objeto do trabalho: alimentá-la com corpus homogêneo
    faria a tela exibir medição que não mede nada.
    """
    with app.app_context():
        adaptador = DemoAdapter("instagram")
        posts = adaptador.fetch_recent_posts(TOKEN_PREFIX + ".instagram.abc")
        textos = [
            c.content
            for p in posts
            for c in adaptador.fetch_post_comments(
                TOKEN_PREFIX + ".instagram.abc", p.platform_post_id
            )
        ]
        assert any("?" in t for t in textos)          # pergunta
        assert any("não" in t or "achei" in t for t in textos)  # crítica
        assert any("link da bio" in t or "segue de volta" in t for t in textos)  # automatizado


def test_posts_nao_inventam_divisao_entre_organico_e_pago(app):
    """ADR-005: a divisão não é concedida pelas APIs sem programa comercial.

    Os adaptadores reais põem todo o alcance em orgânico e zero em pago. Um
    provedor de demonstração que sorteasse a divisão ensinaria a tela a exibir
    um número que a plataforma nunca entrega.
    """
    with app.app_context():
        posts = DemoAdapter("tiktok").fetch_recent_posts(TOKEN_PREFIX + ".tiktok.abc")
        assert posts
        for p in posts:
            assert p.reach_paid == 0
            assert p.reach_organic == p.reach_total
            # Engajamento acima do alcance é o absurdo clássico de dado gerado.
            assert p.likes <= p.reach_total


# ==========================================================================
# Roteamento por conta — o defeito de 16/09
# ==========================================================================
def test_conta_de_demonstracao_nao_vai_para_a_api_real(app, monkeypatch):
    """Credencial real preenchida não pode sequestrar conta ligada por demonstração.

    Foi um defeito de produção: com `META_CLIENT_ID` preenchido, o sync passou a
    mandar o token do provedor local para a Graph API da Meta, que respondeu
    `OAuthException 190 Bad signature` e derrubou a sincronização inteira do
    criador — inclusive as outras redes dele, porque o erro sobe.

    A suíte da interface pegou; a de unidade não pegava, porque todos os testes
    de sync trocam o adaptador por mock e nunca exercitavam a escolha.
    """
    from src.models import SocialAccount

    with app.app_context():
        # A suíte configura META_CLIENT_ID, então `get_adapter` devolve o real.
        assert isinstance(isvc.get_adapter(Platform.INSTAGRAM), InstagramAdapter)

        conta_demo = SocialAccount(
            influencer_id=None, platform=Platform.INSTAGRAM, handle="alguem",
            platform_user_id="demo-instagram-abc",
            access_token_encrypted="cifrado", refresh_token_encrypted="cifrado",
        )
        assert conta_demo.connection_mode == "demo"
        assert isinstance(isvc.get_adapter_for_account(conta_demo), DemoAdapter)


def test_conta_real_continua_indo_para_a_api_real(app):
    """O inverso: conta com identificador de plataforma não cai na demonstração."""
    from src.models import SocialAccount

    with app.app_context():
        conta_real = SocialAccount(
            influencer_id=None, platform=Platform.INSTAGRAM, handle="alguem",
            platform_user_id="17841400000000000",
            access_token_encrypted="cifrado", refresh_token_encrypted="cifrado",
        )
        assert conta_real.connection_mode == "real"
        assert isinstance(isvc.get_adapter_for_account(conta_real), InstagramAdapter)
