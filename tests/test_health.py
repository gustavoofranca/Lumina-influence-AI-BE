"""Smoke test do endpoint de healthcheck."""
from __future__ import annotations


def test_health_returns_ok(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "ok"
    assert body["db"] == "connected"
    assert body["version"] == "0.1.0"
    assert body["env"] == "test"
