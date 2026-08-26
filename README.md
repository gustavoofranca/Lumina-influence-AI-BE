# Lumina Influence AI — Back-End

API REST em **Python + Flask** que serve o front-end do SaaS de auditoria de performance de influenciadores digitais. Persistência em **PostgreSQL**, autenticação **OAuth 2.0 (Google/Microsoft) + JWT**, análise de IA via **Google Gemini** (texto e multimodal), integração com **APIs sociais** (Instagram/TikTok/YouTube) e geração de **relatórios PDF**.

> TCC de Engenharia de Software. O contexto completo — modelo de domínio, padrões e plano de
> etapas B0→B12 — vive no documento do trabalho, fora deste repositório. As decisões de
> arquitetura estão em [`docs/adr/`](docs/adr/) e os relatórios de teste em
> [`docs/security/`](docs/security/) e [`docs/testes/`](docs/testes/).

---

## Stack

| Camada | Tecnologia |
|---|---|
| Linguagem | Python 3.11+ (testado em 3.13) |
| Framework | Flask 3.x (factory pattern) |
| ORM | SQLAlchemy 2.x (`DeclarativeBase`, `Mapped[]`) |
| Banco | PostgreSQL 15+ |
| Migrations | Alembic (via Flask-Migrate) |
| Auth | OAuth 2.0 (Google/Microsoft) + JWT (PyJWT) |
| Validação | Pydantic v2 |
| IA | Google Gemini (`google-genai`), multimodal nativo |
| Jobs | APScheduler (in-process, jobstore SQLAlchemy) |
| Cripto | `cryptography` (Fernet) — tokens sociais em repouso |
| PDF | xhtml2pdf (HTML→PDF puro Python) |
| Testes | pytest + pytest-cov (190 testes, 84% de cobertura) |
| Docs | OpenAPI 3.1 + Swagger UI |

---

## Pré-requisitos

- **Python 3.11+**
- **PostgreSQL 15+** rodando local (ou via Docker — veja abaixo)

---

## Setup local

```bash
# 1. venv
python -m venv venv
.\venv\Scripts\Activate.ps1     # Windows
source venv/bin/activate         # Linux/macOS

# 2. dependências
pip install -r requirements.txt

# 3. variáveis de ambiente
cp .env.example .env             # edite os valores

# gere a FERNET_KEY:
python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"

# 4. banco (local OU docker)
docker compose up -d             # sobe Postgres em localhost:5432
# ou crie manualmente: CREATE DATABASE lumina_dev;

# 5. migrations
flask db upgrade

# 6. popular dados de exemplo
flask seed run

# 7. subir o servidor
flask run

# 8. validar
curl http://localhost:5000/api/v1/health
```

---

## Variáveis de ambiente (`.env`)

| Variável | Descrição |
|---|---|
| `DATABASE_URL` | local: `postgresql://user:senha@localhost:5432/lumina_dev`. Em instância gerenciada, use a string do **Session pooler** — a conexão direta resolve só em IPv6 e o container não a alcança |
| `JWT_SECRET` | segredo de assinatura dos JWTs |
| `FERNET_KEY` | chave Fernet (cripto de tokens sociais) |
| `GOOGLE_CLIENT_ID` / `_SECRET` | OAuth login Google |
| `MICROSOFT_CLIENT_ID` / `_SECRET` | OAuth login Microsoft (opcional) |
| `GEMINI_API_KEY` | Google AI Studio |
| `GEMINI_MODEL` | default `gemini-3.6-flash` — `gemini-2.0-flash` e `gemini-2.5-flash` foram retirados e respondem 404 |
| `OAUTH_REDIRECT_BASE` | base dos redirect URIs OAuth (ex: `http://localhost:5000`) |
| `META/TIKTOK/YOUTUBE_CLIENT_*` | APIs sociais (B8) |
| `AUTH_SUCCESS_REDIRECT` | para onde o callback devolve o navegador (ex: `http://localhost:5173/auth/callback`). Vazio faz o callback responder JSON |
| `FRONTEND_ORIGIN` | origem do front p/ CORS (default `http://localhost:5173`) |
| `LUMINA_DISABLE_SCHEDULER` | `1` desliga os jobs em background. **Recomendado no free tier do Gemini**, que dá 20 requisições por dia: o job de análises consome a cota inteira sozinho |

---

## Comandos úteis

| Ação | Comando |
|---|---|
| Rodar testes | `pytest` |
| Testes + coverage | `pytest --cov=src --cov-report=term-missing` |
| Nova migration | `flask db migrate -m "descrição"` |
| Aplicar migrations | `flask db upgrade` |
| Popular seed | `flask seed run` |
| Limpar seed | `flask seed clear` |
| Listar jobs | `flask jobs list` |
| Rodar job manual | `flask jobs run <name>` |
| Servidor (desenvolvimento) | `flask run` |
| Servidor (WSGI, carga/produção) | `gunicorn -w 4 -b 0.0.0.0:5000 wsgi:app` |

> **Jobs:** o scheduler só inicia com `flask run` (servindo). Comandos CLI não o disparam. Desabilite com `LUMINA_DISABLE_SCHEDULER=1`.
>
> **Atenção sob gunicorn:** cada worker cria a própria instância do APScheduler, então
> todo job roda uma vez por worker. Com o free tier do Gemini (20 requisições/dia) isso
> esgota a cota em minutos. Mantenha `LUMINA_DISABLE_SCHEDULER=1` e dispare os jobs sob
> demanda até que os agendamentos saiam do processo web — ver `docs/testes/carga.md`.

---

## Documentação da API (Swagger)

Com o servidor rodando:

- **Swagger UI:** http://localhost:5000/api/v1/docs
- **OpenAPI JSON:** http://localhost:5000/api/v1/openapi.json

Quase todos os endpoints exigem `Authorization: Bearer <access_token>`. Para obter um token: faça login em `/api/v1/auth/google/login` e copie o `access_token` da resposta.

---

## Principais endpoints

| Grupo | Endpoints |
|---|---|
| Auth | `/auth/google/login` · `/auth/google/callback` · `/auth/refresh` · `/auth/logout` · `/auth/me` |
| CRUD | `/plans` `/agencies` `/users` `/influencers` `/social-accounts` `/campaigns` |
| Dashboard | `/dashboard/overview` · `/dashboard/network-density` · `/influencers/:id/analysis` · `/influencers/:id/posts` · `/campaigns/:id/benchmarking` |
| IA | `POST /posts/:id/analyze` (`?multimodal=true`) · `GET /posts/:id/analyses` |
| Integrações | `/integrations/:platform/connect|callback|disconnect` · `POST /influencers/:id/sync` |
| Relatórios | `POST /reports` · `GET /reports` · `GET /reports/:id/download` |

---

## Estrutura de pastas

```
src/
  app.py              # factory create_app()
  config.py           # Dev/Test/Staging/Prod
  extensions.py       # db, migrate, cors, scheduler
  api/                # blueprints REST (1 por recurso)
  models/             # SQLAlchemy 2.x (13 tabelas)
  schemas/            # Pydantic DTOs (In/Out)
  services/           # lógica de negócio (auth, metric, dashboard, ai_analysis, report, integration)
  integrations/       # adaptadores externos (gemini, instagram, tiktok, youtube, media, oauth)
  jobs/               # APScheduler (sync_metrics, run_pending_analyses, cleanup)
  utils/              # crypto, pagination, authz, rate_limit, pdf_generator, errors
  seed/               # fixtures JSON + seed_data.py
migrations/           # Alembic
tests/                # pytest (190 testes)
docs/adr/             # Architecture Decision Records
docs/security/        # relatórios de análise estática e de IDOR
docs/testes/          # relatórios de teste (robustez de PDF)
storage/reports/      # PDFs gerados (gitignored)
```

---

## Arquitetura em 3 camadas (mitigação de risco)

1. **Camada 1 (sempre funciona):** banco + seed realista (15 influenciadores, 5 campanhas, ~200 posts, ~3000 comentários, ~150 análises). Endpoints servem esses dados.
2. **Camada 2 (APIs sociais):** OAuth Instagram/TikTok/YouTube. `POST /influencers/:id/sync` usa a API real se há token; senão simula (modo dev).
3. **Camada 3 (IA real):** Gemini analisa texto e vídeo (multimodal nativo), persiste diagnósticos.

Decisões técnicas documentadas em [`docs/adr/`](docs/adr/).

---

## Testes & CI

```bash
pytest --cov=src --cov-report=term-missing --cov-fail-under=60
```

Os testes usam **SQLite in-memory** (`TestConfig`) — não precisam de Postgres. CI (GitHub Actions) roda lint + testes + coverage em cada push.

---

## Links

- **Front-end:** https://github.com/gustavoofranca/Lumina-influence-AI-FE
- **Decisões de arquitetura:** [`docs/adr/`](docs/adr/)
