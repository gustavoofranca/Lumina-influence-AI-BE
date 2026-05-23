# Lumina Influence AI — Back-End

API REST em Python + Flask que serve o front-end do SaaS de auditoria de performance de influenciadores digitais. Persistência em PostgreSQL, integração com Google OAuth, APIs sociais (Instagram, TikTok, YouTube) e Google Gemini.

> Para o contexto completo do projeto (modelo de domínio, padrões, plano de etapas B0→B12, prompts), veja `claude.md` na raiz.

---

## Pré-requisitos

- **Python 3.11+** (testado em 3.13.7)
- **PostgreSQL 15+** rodando local (instalação testada com 17.5)
- **Git**

No Windows, o `psql` costuma estar em `C:\Program Files\PostgreSQL\17\bin\` — adicione ao PATH se quiser usar pelo terminal.

---

## Setup local

1. **Clonar o repo**
   ```bash
   git clone https://github.com/<seu-usuario>/Lumina-influence-AI-BE.git
   cd Lumina-influence-AI-BE
   ```

2. **Criar e ativar venv**
   ```bash
   python -m venv venv
   # Windows PowerShell
   .\venv\Scripts\Activate.ps1
   # Linux/macOS
   source venv/bin/activate
   ```

3. **Instalar dependências**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configurar variáveis de ambiente**
   ```bash
   cp .env.example .env
   # edite .env com seus valores reais (DATABASE_URL, JWT_SECRET, FERNET_KEY, etc.)
   ```

   Gere uma `FERNET_KEY`:
   ```bash
   python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
   ```

5. **Criar o banco local**
   ```bash
   # com psql autenticado como superuser
   psql -U postgres -c "CREATE DATABASE lumina_dev;"
   ```

6. **Rodar migrations**
   ```bash
   flask db upgrade
   ```

7. **Subir o servidor**
   ```bash
   flask run
   ```

8. **Validar**
   ```bash
   curl http://localhost:5000/api/v1/health
   # esperado: { "status": "ok", "db": "connected", "version": "0.1.0", "env": "dev" }
   ```

---

## Comandos úteis

| Ação | Comando |
|---|---|
| Rodar testes | `pytest` |
| Nova migration | `flask db migrate -m "descrição"` |
| Aplicar migrations | `flask db upgrade` |
| Reverter última migration | `flask db downgrade -1` |
| Popular dados de exemplo (B2+) | `flask seed run` |
| Limpar seed (B2+) | `flask seed clear` |
| Listar jobs (B7+) | `flask jobs list` |

---

## Estrutura de pastas

```
src/
  app.py              # factory create_app()
  config.py           # Dev/Test/Staging/Prod
  extensions.py       # db, migrate, cors, scheduler
  api/                # blueprints REST (1 por recurso)
  models/             # SQLAlchemy (a partir da B1)
  schemas/            # Pydantic DTOs
  services/           # lógica de negócio pura
  integrations/       # adaptadores p/ APIs externas
  jobs/               # APScheduler tasks
  utils/              # erros, crypto, pagination, ...
  seed/               # fixtures + seed_data.py
migrations/           # Alembic
tests/                # pytest
storage/              # PDFs gerados (gitignored)
docs/                 # ADRs, diagramas (gitignored localmente)
```

---

## Status do desenvolvimento

- ✅ **B0** — Setup e fundação (este commit)
- ⏳ B1 — Modelagem do banco
- ⏳ B2 → B12 — ver `claude.md`

---

## Links

- **Front-end:** https://github.com/gustavoofranca/Lumina-influence-AI-FE
- **Plano completo:** `claude.md`
