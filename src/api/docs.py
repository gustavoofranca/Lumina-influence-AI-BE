"""Documentação OpenAPI 3.1 + Swagger UI.

O `components.schemas` é gerado automaticamente dos schemas Pydantic (B4-B10).
Os paths principais são descritos de forma concisa. Servido em:
- GET /api/v1/openapi.json — a especificação
- GET /api/v1/docs — Swagger UI (assets via CDN)
"""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify

from src.schemas.agency import AgencyOut
from src.schemas.analysis import AIAnalysisOut, PostOut
from src.schemas.campaign import CampaignCreateIn, CampaignOut
from src.schemas.influencer import InfluencerCreateIn, InfluencerOut
from src.schemas.plan import PlanOut
from src.schemas.report import ReportCreateIn, ReportOut, ReportPreviewIn
from src.schemas.social_account import SocialAccountCreateIn, SocialAccountOut
from src.schemas.user import UserCreateIn, UserOut

bp = Blueprint("docs", __name__, url_prefix="/api/v1")

_MODELS = [
    PlanOut, AgencyOut, UserOut, InfluencerOut, InfluencerCreateIn,
    SocialAccountOut, CampaignOut, CampaignCreateIn, PostOut, AIAnalysisOut,
    ReportOut, ReportCreateIn, ReportPreviewIn,
    UserCreateIn, SocialAccountCreateIn,
]


def _build_schemas() -> dict:
    """Gera components.schemas a partir dos modelos Pydantic, juntando os $defs."""
    schemas: dict = {}
    for model in _MODELS:
        js = model.model_json_schema(ref_template="#/components/schemas/{model}")
        for name, sub in js.pop("$defs", {}).items():
            schemas.setdefault(name, sub)
        schemas[model.__name__] = js
    return schemas


def _ref(name: str) -> dict:
    return {"$ref": f"#/components/schemas/{name}"}


def _ok(schema_name: str, *, is_list: bool = False) -> dict:
    data = {"type": "array", "items": _ref(schema_name)} if is_list else _ref(schema_name)
    return {
        "200": {
            "description": "OK",
            "content": {"application/json": {"schema": {
                "type": "object",
                "properties": {"data": data, "meta": {"type": "object"}},
            }}},
        }
    }


def _crud_paths(resource: str, out: str, create_in: str | None, tag: str,
                *, mutable: bool = True) -> dict:
    """Paths do CRUD de um recurso.

    `mutable=False` para recurso somente-leitura: documentar PATCH e DELETE que
    não existem engana quem integra tanto quanto omitir rota que existe.
    """
    base = f"/api/v1/{resource}"
    item = base + "/{id}"
    paths = {
        base: {
            "get": {"tags": [tag], "summary": f"Lista {resource} (paginado)",
                    "security": [{"bearerAuth": []}], "responses": _ok(out, is_list=True)},
        },
        item: {
            "get": {"tags": [tag], "summary": f"Detalhe de {resource}",
                    "security": [{"bearerAuth": []}], "responses": _ok(out)},
        },
    }
    if mutable:
        paths[item]["patch"] = {
            "tags": [tag], "summary": f"Atualiza {resource}",
            "security": [{"bearerAuth": []}], "responses": _ok(out)}
        paths[item]["delete"] = {
            "tags": [tag], "summary": f"Remove {resource}",
            "security": [{"bearerAuth": []}],
            "responses": {"204": {"description": "No Content"}}}
    if create_in:
        paths[base]["post"] = {
            "tags": [tag], "summary": f"Cria {resource}", "security": [{"bearerAuth": []}],
            "requestBody": {"required": True, "content": {"application/json": {"schema": _ref(create_in)}}},
            "responses": {"201": {"description": "Created",
                          "content": {"application/json": {"schema": {"type": "object",
                          "properties": {"data": _ref(out)}}}}}},
        }
    return paths


def build_openapi() -> dict:
    paths: dict = {
        "/api/v1/health": {
            "get": {"tags": ["Health"], "summary": "Healthcheck (db + versão)",
                    "responses": {"200": {"description": "OK"}, "503": {"description": "DB indisponível"}}},
        },
        "/api/v1/auth/google/login": {
            "get": {"tags": ["Auth"], "summary": "Inicia OAuth Google (redirect)",
                    "responses": {"302": {"description": "Redirect ao Google"}}},
        },
        "/api/v1/auth/me": {
            "get": {"tags": ["Auth"], "summary": "Usuário logado", "security": [{"bearerAuth": []}],
                    "responses": _ok("UserOut")},
        },
        "/api/v1/auth/refresh": {
            "post": {"tags": ["Auth"], "summary": "Renova access token (refresh)",
                     "security": [{"bearerAuth": []}], "responses": {"200": {"description": "Novo par de tokens"}}},
        },
        "/api/v1/dashboard/overview": {
            "get": {"tags": ["Dashboard"], "summary": "KPIs + growth + featured + top performing",
                    "security": [{"bearerAuth": []}],
                    "parameters": [
                        {"name": "period", "in": "query", "schema": {"type": "string", "enum": ["7d", "30d", "90d"]}},
                        {"name": "campaign_id", "in": "query", "schema": {"type": "string"}},
                    ],
                    "responses": {"200": {"description": "Agregados do dashboard"}}},
        },
        "/api/v1/dashboard/network-density": {
            "get": {"tags": ["Dashboard"], "summary": "Densidade de rede",
                    "security": [{"bearerAuth": []}], "responses": {"200": {"description": "OK"}}},
        },
        "/api/v1/influencers/{id}/analysis": {
            "get": {"tags": ["Dashboard"], "summary": "Diagnóstico IA completo do influencer",
                    "security": [{"bearerAuth": []}], "responses": {"200": {"description": "OK"}}},
        },
        "/api/v1/influencers/{id}/analyses": {
            "get": {"tags": ["AI"], "summary": "Histórico de análises do criador",
                    "description": "Une as análises de todos os posts das contas do criador, "
                                   "da mais recente para a mais antiga.",
                    "security": [{"bearerAuth": []}],
                    "responses": {"200": {"description": "Lista de análises"}}},
        },
        "/api/v1/influencers/{id}/posts": {
            "get": {"tags": ["Dashboard"], "summary": "Grid de posts analisados",
                    "security": [{"bearerAuth": []}], "responses": {"200": {"description": "OK"}}},
        },
        "/api/v1/influencers/{id}/sync": {
            "post": {"tags": ["Integrations"], "summary": "Sincroniza contas sociais (real ou simulado)",
                     "security": [{"bearerAuth": []}], "responses": {"200": {"description": "Resumo do sync"}}},
        },
        "/api/v1/campaigns/{id}/benchmarking": {
            "get": {"tags": ["Dashboard"], "summary": "Benchmarking (tabela + radar)",
                    "security": [{"bearerAuth": []}], "responses": {"200": {"description": "OK"}}},
        },
        "/api/v1/posts/{id}/analyze": {
            "post": {"tags": ["AI"], "summary": "Análise IA via Gemini (?multimodal=true p/ vídeo)",
                     "security": [{"bearerAuth": []}],
                     "parameters": [{"name": "multimodal", "in": "query", "schema": {"type": "boolean"}}],
                     "responses": {"201": {"description": "Análise criada",
                     "content": {"application/json": {"schema": {"type": "object",
                     "properties": {"data": _ref("AIAnalysisOut")}}}}},
                     "429": {"description": "Rate limit"}}},
        },
        "/api/v1/posts/{id}/analyses": {
            "get": {"tags": ["AI"], "summary": "Histórico de análises do post",
                    "security": [{"bearerAuth": []}], "responses": _ok("AIAnalysisOut", is_list=True)},
        },
        "/api/v1/reports/{id}/download": {
            "get": {"tags": ["Reports"], "summary": "Baixa o PDF do relatório",
                    "security": [{"bearerAuth": []}],
                    "responses": {"200": {"description": "PDF", "content": {"application/pdf": {}}}}},
        },
        "/api/v1/auth/google/callback": {
            "get": {"tags": ["Auth"], "summary": "Callback do OAuth Google (redirect do navegador)",
                    "description": "Troca o `code` por tokens e redireciona ao front com o par de "
                                   "JWT no fragmento da URL. Não é chamado pelo cliente da API.",
                    "parameters": [
                        {"name": "code", "in": "query", "required": True, "schema": {"type": "string"}},
                        {"name": "state", "in": "query", "required": True, "schema": {"type": "string"}},
                    ],
                    "responses": {"302": {"description": "Redirect ao front-end"},
                                  "200": {"description": "Par de tokens, quando não há redirect configurado"}}},
        },
        "/api/v1/auth/microsoft/login": {
            "get": {"tags": ["Auth"], "summary": "Inicia OAuth Microsoft (redirect)",
                    "responses": {"302": {"description": "Redirect à Microsoft"}}},
        },
        "/api/v1/auth/microsoft/callback": {
            "get": {"tags": ["Auth"], "summary": "Callback do OAuth Microsoft (redirect do navegador)",
                    "parameters": [
                        {"name": "code", "in": "query", "required": True, "schema": {"type": "string"}},
                        {"name": "state", "in": "query", "required": True, "schema": {"type": "string"}},
                    ],
                    "responses": {"302": {"description": "Redirect ao front-end"},
                                  "200": {"description": "Par de tokens, quando não há redirect configurado"}}},
        },
        "/api/v1/auth/logout": {
            "post": {"tags": ["Auth"], "summary": "Encerra a sessão do lado do cliente",
                     "description": "JWT é stateless (ADR-001): o servidor não revoga nada. "
                                    "Responde 204 e o cliente descarta os dois tokens.",
                     "security": [{"bearerAuth": []}],
                     "responses": {"204": {"description": "No Content"}}},
        },
        "/api/v1/agencies/{id}/usage": {
            "get": {"tags": ["Agencies"], "summary": "Consumo da agência frente aos limites do plano",
                    "security": [{"bearerAuth": []}],
                    "responses": {"200": {"description": "Uso corrente e limites contratados"}}},
        },
        "/api/v1/posts/{id}": {
            "get": {"tags": ["AI"], "summary": "Detalhe do post",
                    "security": [{"bearerAuth": []}], "responses": _ok("PostOut")},
        },
        "/api/v1/reports/preview": {
            "post": {"tags": ["Reports"],
                     "summary": "Prévia do relatório — mesmo conteúdo do PDF, sem gravar",
                     "security": [{"bearerAuth": []}],
                     "requestBody": {"required": True, "content": {"application/json": {
                         "schema": _ref("ReportPreviewIn")}}},
                     "responses": {"200": {"description": "Contexto do relatório"}}},
        },
        "/api/v1/integrations/{platform}/callback": {
            "get": {"tags": ["Integrations"],
                    "summary": "Callback do OAuth da plataforma (redirect do navegador)",
                    "description": "Não exige Bearer: quem chega é o navegador vindo do "
                                   "provedor. A identidade sai do `state` assinado, de uso "
                                   "único e validade de 15 min (ADR-004).",
                    "parameters": [
                        {"name": "code", "in": "query", "required": True, "schema": {"type": "string"}},
                        {"name": "state", "in": "query", "required": True, "schema": {"type": "string"}},
                    ],
                    "responses": {"302": {"description": "Redirect ao front-end"},
                                  "201": {"description": "Conta vinculada, quando não há redirect configurado"},
                                  "401": {"description": "State inválido, expirado ou já utilizado"}}},
        },
        "/api/v1/integrations/{platform}/disconnect/{id}": {
            "post": {"tags": ["Integrations"], "summary": "Desvincula a conta social da plataforma",
                     "security": [{"bearerAuth": []}],
                     "responses": {"200": {"description": "Conta desvinculada"}}},
        },
        "/api/v1/integrations/{platform}/connect": {
            "get": {"tags": ["Integrations"], "summary": "URL de OAuth da plataforma",
                    "security": [{"bearerAuth": []}],
                    "parameters": [{"name": "influencer_id", "in": "query", "required": True,
                                    "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "auth_url"}}},
        },
    }

    # CRUD genéricos
    paths.update(_crud_paths("plans", "PlanOut", None, "Plans", mutable=False))
    paths.update(_crud_paths("users", "UserOut", "UserCreateIn", "Users"))
    paths.update(_crud_paths("agencies", "AgencyOut", None, "Agencies"))
    paths.update(_crud_paths("influencers", "InfluencerOut", "InfluencerCreateIn", "Influencers"))
    # `enriched` vale na listagem e no detalhe: acrescenta as métricas
    # calculadas (engajamento, sentimento, bot, ressonância) ao recurso.
    _enriched = {
        "name": "enriched", "in": "query",
        "description": "Inclui o objeto `metrics` com as métricas calculadas.",
        "schema": {"type": "boolean"},
    }
    paths["/api/v1/influencers"]["get"].setdefault("parameters", []).append(_enriched)
    paths["/api/v1/influencers/{id}"]["get"].setdefault("parameters", []).append(_enriched)
    paths.update(_crud_paths("social-accounts", "SocialAccountOut", "SocialAccountCreateIn",
                             "Integrations"))
    paths.update(_crud_paths("campaigns", "CampaignOut", "CampaignCreateIn", "Campaigns"))
    paths.update(_crud_paths("reports", "ReportOut", "ReportCreateIn", "Reports", mutable=False))

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Lumina Influence AI — API",
            "version": current_app.config.get("VERSION", "0.1.0"),
            "description": "API REST de auditoria de performance de influenciadores. "
                           "Autenticação via OAuth (Google/Microsoft) + JWT Bearer.",
        },
        "servers": [{"url": "/", "description": "Servidor atual"}],
        "tags": [
            {"name": "Health"}, {"name": "Auth"}, {"name": "Dashboard"}, {"name": "Influencers"},
            {"name": "Campaigns"}, {"name": "AI"}, {"name": "Reports"}, {"name": "Integrations"},
            {"name": "Plans"}, {"name": "Users"}, {"name": "Agencies"},
        ],
        "paths": paths,
        "components": {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
            },
            "schemas": _build_schemas(),
        },
    }


@bp.get("/openapi.json")
def openapi_spec():
    return jsonify(build_openapi())


_SWAGGER_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"/><title>Lumina API — Docs</title>
<link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css"/>
</head><body><div id="swagger-ui"></div>
<script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
window.onload = () => { window.ui = SwaggerUIBundle({
  url: '/api/v1/openapi.json', dom_id: '#swagger-ui', deepLinking: true,
  presets: [SwaggerUIBundle.presets.apis] });
};
</script></body></html>"""


@bp.get("/docs")
def swagger_ui():
    return _SWAGGER_HTML, 200, {"Content-Type": "text/html; charset=utf-8"}
