#!/bin/sh
# Aplica as migrations antes de subir a API. O compose só inicia este container
# depois que o healthcheck do Postgres passa, então o banco já aceita conexões.
set -e

echo "==> flask db upgrade"
flask db upgrade

exec "$@"
