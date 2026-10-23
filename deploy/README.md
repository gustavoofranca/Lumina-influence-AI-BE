# Deploy em produção (VPS Hostinger)

Um VPS com Ubuntu 24.04 e Docker roda três containers:

| Container | Papel |
|---|---|
| `caddy` | HTTPS automático (Let's Encrypt). Serve o front em `DOMINIO` e repassa `api.DOMINIO` para a API. |
| `api` | Flask com gunicorn (1 processo, 8 threads), atrás do Caddy (`TRUSTED_PROXIES=1`). |
| `worker` | Mesmo código, só o agendador de jobs. |

O banco é o Supabase (`DATABASE_URL`). Os PDFs e os vídeos enviados ficam no
volume `storage`.

## Estrutura no VPS

```
/opt/lumina/
├── Lumina-Influence-AI-BE/     # este repositório
│   ├── .env                    # produção: deploy/env.prod.example + o .env de dev
│   └── deploy/                 # estes arquivos
└── Lumina-Influence-AI-FE/     # o front, ao lado (o build lê daqui)
```

## Primeira instalação

```bash
apt-get update && apt-get install -y git
mkdir -p /opt/lumina && cd /opt/lumina
git clone https://github.com/gustavoofranca/Lumina-influence-AI-BE.git Lumina-Influence-AI-BE
git clone https://github.com/gustavoofranca/Lumina-influence-AI-FE.git Lumina-Influence-AI-FE
# criar Lumina-Influence-AI-BE/.env (ver env.prod.example) e então:
chmod +x Lumina-Influence-AI-BE/deploy/deploy.sh
Lumina-Influence-AI-BE/deploy/deploy.sh
```

**DNS:** registros `A` de `DOMINIO` e de `api.DOMINIO` apontando para o IP do
VPS (com `DOMINIO=lumina.gustavofranca.tech`, os nomes `lumina` e
`api.lumina` na zona de `gustavofranca.tech`). O Caddy só consegue emitir o
certificado depois que o DNS propaga.

**Firewall:** liberar 22 (SSH), 80 e 443 (TCP) e 443 (UDP, HTTP/3).

## Atualizar

```bash
/opt/lumina/Lumina-Influence-AI-BE/deploy/deploy.sh            # DEPLOY_BRANCH do .env
/opt/lumina/Lumina-Influence-AI-BE/deploy/deploy.sh main       # outro branch
```

## Migrations: nunca automáticas

A imagem de produção **não** roda `flask db upgrade` ao subir: a migration
altera o banco real, que é o mesmo do desenvolvimento. Com a confirmação de
quem administra, aplique **depois** do deploy:

```bash
cd /opt/lumina/Lumina-Influence-AI-BE/deploy
docker compose -f docker-compose.prod.yml --env-file ../.env run --rm api flask db current
docker compose -f docker-compose.prod.yml --env-file ../.env run --rm api flask db upgrade
```

## Operação

```bash
cd /opt/lumina/Lumina-Influence-AI-BE/deploy
C="docker compose -f docker-compose.prod.yml --env-file ../.env"
$C ps                        # estado e healthcheck
$C logs -f --tail=100 api    # logs da API (caddy, worker idem)
$C restart api               # reinicia só a API
$C run --rm api flask users set-password <email>   # pede a senha no terminal
```

**Voltar para a versão anterior:** `git -C ../ checkout <commit>` (e o mesmo no
front), depois `$C up -d --build`.

## Retorno dos logins sociais

Cadastre estas URLs no console de cada provedor:

| Provedor | URL de retorno |
|---|---|
| Google | `https://api.DOMINIO/api/v1/auth/google/callback` |
| Microsoft | `https://api.DOMINIO/api/v1/auth/microsoft/callback` |
| Instagram (Meta) | `https://api.DOMINIO/api/v1/integrations/instagram/callback` |
| TikTok | `https://api.DOMINIO/api/v1/integrations/tiktok/callback` |
| YouTube (Google) | `https://api.DOMINIO/api/v1/integrations/youtube/callback` |
