"""Carga da B12 — cenários que não dependem da cota do Gemini.

Duas classes de usuário, selecionáveis na linha de comando:

  DashboardUser  baseline: só GET /dashboard/overview, para medir um endpoint
                 isolado (p50/p95/p99 e vazão) sem ruído de outras rotas.
  NavegacaoUser  mistura de leituras que uma sessão real faz, para o cenário de
                 stress — onde interessa o ponto de saturação, não a latência de
                 uma rota específica.

O token é obtido uma vez no início e compartilhado: JWT é stateless, e medir o
login junto poluiria a amostra do endpoint sob teste.

Uso:
  locust -f locustfile.py --host http://localhost:5001 \
         DashboardUser --headless -u 50 -r 10 -t 2m
"""
from __future__ import annotations

import logging
import os

import requests
from locust import HttpUser, between, events, task

LOGIN_EMAIL = os.getenv("LUMINA_LOAD_EMAIL", "marina@lumina-agency.com.br")

_token: str | None = None
logger = logging.getLogger("lumina.load")


@events.test_start.add_listener
def obter_token(environment, **_):
    """Autentica uma vez antes do teste e guarda o access token."""
    global _token
    url = f"{environment.host.rstrip('/')}/api/v1/auth/dev-login"
    r = requests.post(url, json={"email": LOGIN_EMAIL}, timeout=30)
    r.raise_for_status()
    _token = r.json()["data"]["tokens"]["access_token"]
    logger.info("Token obtido para %s", LOGIN_EMAIL)


class _AutenticadoUser(HttpUser):
    abstract = True

    def on_start(self):
        if not _token:
            raise RuntimeError("Sem token — o listener de test_start não rodou")
        self.client.headers["Authorization"] = f"Bearer {_token}"


class DashboardUser(_AutenticadoUser):
    """Baseline: um endpoint só, sem pausa artificial entre requisições."""

    wait_time = between(1, 2)

    @task
    def overview(self):
        self.client.get("/api/v1/dashboard/overview?period=30d", name="/dashboard/overview")


class NavegacaoUser(_AutenticadoUser):
    """Stress: mistura de leituras, com peso proporcional ao uso esperado."""

    wait_time = between(1, 3)

    @task(4)
    def overview(self):
        self.client.get("/api/v1/dashboard/overview?period=30d", name="/dashboard/overview")

    @task(3)
    def listar_influenciadores(self):
        self.client.get("/api/v1/influencers?per_page=20", name="/influencers")

    @task(2)
    def listar_influenciadores_enriquecidos(self):
        self.client.get(
            "/api/v1/influencers?per_page=20&enriched=true", name="/influencers?enriched")

    @task(2)
    def listar_campanhas(self):
        self.client.get("/api/v1/campaigns?per_page=20", name="/campaigns")

    @task(1)
    def densidade_de_rede(self):
        self.client.get("/api/v1/dashboard/network-density", name="/dashboard/network-density")
