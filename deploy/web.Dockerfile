# Front-end (React/Vite) compilado e servido pelo Caddy, que também faz o HTTPS.
#
# O código do front vem do contexto adicional `frontend` (o repositório
# Lumina-Influence-AI-FE ao lado deste), declarado no docker-compose.prod.yml.
# O .dockerignore do front vale para ele: node_modules, e2e e .env ficam fora.
FROM node:22-alpine AS build
WORKDIR /app
COPY --from=frontend package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY --from=frontend . .

# Entram no build (import.meta.env) e na CSP gerada pelo vite.config.js.
ARG VITE_API_BASE_URL
ARG VITE_CONTACT_EMAIL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_CONTACT_EMAIL=$VITE_CONTACT_EMAIL
RUN npm run build

FROM caddy:2.10-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
