#!/usr/bin/env bash
# Atualiza o código e sobe a versão nova. Rode no VPS, de qualquer pasta:
#   /opt/lumina/Lumina-Influence-AI-BE/deploy/deploy.sh [branch]
# Sem argumento usa DEPLOY_BRANCH do .env (ou main). O mesmo branch é usado
# nos dois repositórios.
#
# NÃO aplica migrations: elas mexem no banco real e são aplicadas à parte,
# com confirmação (deploy/README.md).
set -euo pipefail

AQUI="$(cd "$(dirname "$0")" && pwd)"
BE="$(dirname "$AQUI")"
FE="$(dirname "$BE")/Lumina-Influence-AI-FE"
ENV_FILE="$BE/.env"

[ -f "$ENV_FILE" ] || { echo "Falta $ENV_FILE (modelo: deploy/env.prod.example)." >&2; exit 1; }
BRANCH="${1:-$(grep -E '^DEPLOY_BRANCH=' "$ENV_FILE" | cut -d= -f2- || true)}"
BRANCH="${BRANCH:-main}"

for repo in "$BE" "$FE"; do
	echo "==> $(basename "$repo"): $BRANCH"
	git -C "$repo" fetch --prune origin
	git -C "$repo" checkout "$BRANCH"
	git -C "$repo" pull --ff-only origin "$BRANCH"
done

compose() { docker compose -f "$AQUI/docker-compose.prod.yml" --env-file "$ENV_FILE" "$@"; }

echo "==> build e subida"
compose up -d --build --remove-orphans
docker image prune -f >/dev/null

echo "==> aguardando a API"
for _ in $(seq 1 45); do
	if compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/api/v1/health', timeout=5)" 2>/dev/null; then
		echo "API no ar. Versão: BE $(git -C "$BE" log --oneline -1) | FE $(git -C "$FE" log --oneline -1)"
		exit 0
	fi
	sleep 2
done
echo "A API não respondeu em 90 s. Veja: docker compose -f $AQUI/docker-compose.prod.yml logs api" >&2
exit 1
