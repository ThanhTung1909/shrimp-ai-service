"""Regression coverage for HTTP-only FastAPI lifecycle isolation."""

from fastapi.testclient import TestClient

from app import database
from app.main import app
from app.services.rabbitmq_publisher import RabbitMQPublisher
from app.services.redis_cache import RedisCacheService


def test_http_only_lifecycle_does_not_initialize_external_infrastructure(monkeypatch):
    async def unexpected_redis_ping(self):  # pragma: no cover - must never run
        raise AssertionError("HTTP-only test attempted to reach Redis")

    async def unexpected_rabbitmq_connect(self):  # pragma: no cover - must never run
        raise AssertionError("HTTP-only test attempted to reach RabbitMQ")

    def unexpected_database_check():  # pragma: no cover - must never run
        raise AssertionError("HTTP-only test attempted to reach PostgreSQL")

    monkeypatch.setattr(RedisCacheService, "ping", unexpected_redis_ping)
    monkeypatch.setattr(RabbitMQPublisher, "connect", unexpected_rabbitmq_connect)
    monkeypatch.setattr(database, "check_db_connection", unexpected_database_check)

    payload = {
        "pondId": "78ad6b2a-b628-4c7f-9f2c-91953a3ea2cb",
        "temperature": 29.5,
        "ph": 7.8,
        "dissolvedOxygen": 5.2,
        "salinity": 15.0,
        "turbidity": 20.0,
    }

    with TestClient(app, raise_server_exceptions=False) as client:
        health = client.get("/health")
        prediction = client.post("/api/predict", json=payload)

    assert health.status_code == 200
    assert health.json()["database"]["error"] == "disabled in isolated HTTP test mode"
    assert health.json()["redis"]["connected"] is False
    assert health.json()["rabbitmq"]["connected"] is False
    assert prediction.status_code == 200
