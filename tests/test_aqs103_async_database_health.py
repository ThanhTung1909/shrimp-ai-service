"""AQS-103 regression coverage for the non-blocking database health probe."""

import asyncio
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app import database
from app.main import app, health_check


def test_async_health_probe_preserves_connected_status(monkeypatch):
    expected = {
        "connected": True,
        "timescaledb_installed": True,
        "timescaledb_version": "2.15.0",
        "error": None,
    }
    monkeypatch.setattr(database, "check_db_connection", lambda: expected)

    assert asyncio.run(database.check_db_connection_async()) == expected


def test_async_health_probe_preserves_disconnected_status(monkeypatch):
    expected = {
        "connected": False,
        "timescaledb_installed": False,
        "timescaledb_version": None,
        "error": "Connection refused",
    }
    monkeypatch.setattr(database, "check_db_connection", lambda: expected)

    assert asyncio.run(database.check_db_connection_async()) == expected


def test_sync_probe_returns_safe_status_for_query_exception(monkeypatch):
    class FailingConnection:
        def execute(self, _):
            raise RuntimeError("statement failed")

    class FailingTransaction:
        def __enter__(self):
            return FailingConnection()

        def __exit__(self, *_):
            return False

    class FailingEngine:
        def begin(self):
            return FailingTransaction()

    monkeypatch.setattr(database, "get_engine", lambda: FailingEngine())

    status = database.check_db_connection()

    assert status["connected"] is False
    assert status["timescaledb_installed"] is False
    assert status["timescaledb_version"] is None
    assert status["error"] == "statement failed"


def test_sync_probe_returns_safe_status_for_query_exception(monkeypatch):
    class FailingConnection:
        def execute(self, _):
            raise RuntimeError("statement failed")

    class FailingTransaction:
        def __enter__(self):
            return FailingConnection()

        def __exit__(self, *_):
            return False

    class FailingEngine:
        def begin(self):
            return FailingTransaction()

    monkeypatch.setattr(database, "get_engine", lambda: FailingEngine())

    status = database.check_db_connection()

    assert status["connected"] is False
    assert status["timescaledb_installed"] is False
    assert status["timescaledb_version"] is None
    assert status["error"] == "statement failed"


@pytest.mark.asyncio
async def test_async_health_probe_turns_slow_sync_call_into_timeout(monkeypatch):
    monkeypatch.setattr(database.settings, "db_health_check_timeout_seconds", 0.05)

    def slow_probe():
        time.sleep(0.2)
        return {"connected": True}

    monkeypatch.setattr(database, "check_db_connection", slow_probe)
    started = time.perf_counter()
    status = await database.check_db_connection_async()

    assert time.perf_counter() - started < 0.15
    assert status == {
        "connected": False,
        "timescaledb_installed": False,
        "timescaledb_version": None,
        "error": "database health check timed out after 0.05 seconds",
    }


def test_health_handler_preserves_database_response_contract(monkeypatch):
    expected = {
        "connected": False,
        "timescaledb_installed": False,
        "timescaledb_version": None,
        "error": "query failed",
    }

    async def failed_probe():
        return expected

    monkeypatch.setattr(database, "check_db_connection_async", failed_probe)
    app.state.http_test_mode = False
    app.state.redis_service = None
    app.state.rabbitmq_publisher = None
    app.state.feeding_trainer = object()
    app.state.model_metadata = {"version": "1.0.0"}

    response = asyncio.run(health_check())

    assert response["database"] == expected



@pytest.mark.asyncio
async def test_slow_database_health_probe_does_not_block_openapi(
    monkeypatch,
):
    probe_started = asyncio.Event()
    release_probe = asyncio.Event()

    async def slow_probe():
        probe_started.set()

        # Giữ DB probe đang chờ đến khi test chủ động giải phóng.
        await release_probe.wait()

        return {
            "connected": False,
            "timescaledb_installed": False,
            "timescaledb_version": None,
            "error": "simulated timeout",
        }

    monkeypatch.setattr(
        database,
        "check_db_connection_async",
        slow_probe,
    )

    app.state.http_test_mode = False
    app.state.redis_service = None
    app.state.rabbitmq_publisher = None
    app.state.feeding_trainer = object()
    app.state.model_metadata = {"version": "1.0.0"}

    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:

        health_task = asyncio.create_task(
            client.get("/health")
        )

        try:
            # Xác nhận DB probe đã thực sự bắt đầu.
            await asyncio.wait_for(
                probe_started.wait(),
                timeout=2.0,
            )

            assert not health_task.done(), (
                "/health finished before DB probe was released"
            )

            # /openapi.json phải hoàn thành dù DB probe đang chờ.
            openapi = await asyncio.wait_for(
                client.get("/openapi.json"),
                timeout=2.0,
            )

            assert openapi.status_code == 200

            # Health check vẫn đang chờ DB.
            assert not health_task.done(), (
                "/health unexpectedly completed before DB release"
            )

        finally:
            # Luôn giải phóng DB probe, kể cả khi assertion thất bại.
            release_probe.set()

            health = await asyncio.wait_for(
                health_task,
                timeout=2.0,
            )

        assert health.status_code == 200

        health_data = health.json()

        assert health_data["database"]["connected"] is False
        assert health_data["database"]["error"] == "simulated timeout"
