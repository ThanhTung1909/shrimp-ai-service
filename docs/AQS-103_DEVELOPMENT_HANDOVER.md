# AQS-103 — Async Database Health Check

**Date:** 2026-11-21  
**Repository / branch:** `shrimp-ai-service` / `feature/AQS-103_async-database-health-check`  
**Base:** `origin/develop@e3363ee20169d54d558ede1b0c954466c10e5428`, with local merge commit `08245d5` preserving the published AQS-102 compatibility branch.  
**Delivery state:** local implementation complete; no commit or push requested.  
**Production AI approval:** unchanged — `PRODUCTION_AI_BLOCKED_PENDING_APPROVAL`.

## Root cause

`GET /health` was already an `async def`, but it called `app.database.check_db_connection()` directly. That function uses synchronous SQLAlchemy/psycopg I/O (`Engine.connect()` plus `SELECT 1` and the TimescaleDB extension query). A slow connection or query therefore occupied the FastAPI event loop despite the endpoint declaration being async. There was no explicit database connect or statement timeout.

## Implementation

- Added `check_db_connection_async()`, which executes the existing synchronous probe in `asyncio.to_thread()` and awaits it with `asyncio.wait_for()`.
- Kept the existing database response fields and HTTP 200 health policy unchanged.
- Added configurable `DB_CONNECT_TIMEOUT_SECONDS` (default 3) to the SQLAlchemy engine connection arguments and `DB_HEALTH_CHECK_TIMEOUT_SECONDS` (default 3.0) as the async response budget.
- Runs `SET LOCAL statement_timeout` inside the existing pooled connection's health-probe transaction; it is scoped to that transaction and does not persist in the connection pool.
- A timed-out async wrapper returns the existing database status shape with a sanitized timeout error. It does not reveal connection settings. A thread already inside a blocking driver call cannot be forcibly cancelled, so the driver connect timeout and statement timeout bound that work.

## Validation

`pytest -q` using the existing `.venv-aqs101` environment: **111 passed** (97 pre-existing/dependency warnings).

The six AQS-103 tests cover connected, disconnected, sync query-error contract handling, wrapper timeout, health response contract, and concurrency. The concurrency regression simulates a 200 ms health probe and verifies `/openapi.json` responds in under 100 ms before the health request completes. No production database, Redis, RabbitMQ, model, or configuration was modified.

Known non-AQS-103 warnings remain: FastAPI/Starlette and asyncio deprecations, plus pre-existing scikit-learn/XGBoost artifact version warnings.

## Compatibility audit

Core references FastAPI only through the approved `/api/predict` transport; no Core caller invokes `/health`. The web portal accesses Core AI-analysis endpoints rather than FastAPI `/health`. The health JSON field names and status policy remain compatible, so no Core or Frontend change is required.

## RabbitMQ full-regression stabilization — 2026-11-21

The reported stuck test was `tests/test_task_be05.py::test_rabbitmq_offline_graceful_degradation[asyncio]`. On this worktree it did not reproduce under a process-owned 60-second guard: it exited `0` in 9.87 seconds. The original test nonetheless made a real TCP attempt to `localhost:9999`, which meant test duration and robust-client behavior depended on the host networking stack rather than the publisher's error handling.

The test now monkeypatches only `aio_pika.connect_robust`, the I/O boundary, to raise `ConnectionRefusedError`. It still invokes the real `RabbitMQPublisher.connect()`, `ping()`, `publish_risk_alert()`, and `close()` methods; the assertions verify both explicit connection attempts return graceful `False`. No RabbitMQ publisher production code, message schema, exchange, queue, routing key, or retry policy changed.

Evidence with `AQUASENSE_HTTP_TEST_MODE=true` and `PYTHONDONTWRITEBYTECODE=1`, using the functional `.venv-aqs101` environment (the requested `.venv` launcher is broken because its Python 3.10 base is absent):

- offline test under a 60-second process guard: PASS; no timeout;
- `tests/test_task_be05.py`: **5/5 PASS**;
- `tests/test_aqs103_async_database_health.py`: **6/6 PASS**;
- `tests/test_aqs102_compatibility_and_routes.py`: **22/22 PASS**;
- full pytest under a 120-second process guard: **111/111 PASS, 97 warnings, 13.65s, exit 0**.

Full log: `D:\Khóa Luận\Project\shrimp-core-backend\tmp\aqs103-hang-audit-backup\full-pytest-after-rabbitmq-test-fix.log`. Remaining warnings are the pre-existing FastAPI/Starlette/asyncio deprecations and scikit-learn/XGBoost artifact compatibility warnings. No AQS-104 RabbitMQ consumer work is needed or included.

## RabbitMQ full-regression stabilization — 2026-11-21

The reported stuck test was `tests/test_task_be05.py::test_rabbitmq_offline_graceful_degradation[asyncio]`. On this worktree it did not reproduce under a process-owned 60-second guard: it exited `0` in 9.87 seconds. The original test nonetheless made a real TCP attempt to `localhost:9999`, which meant test duration and robust-client behavior depended on the host networking stack rather than the publisher's error handling.

The test now monkeypatches only `aio_pika.connect_robust`, the I/O boundary, to raise `ConnectionRefusedError`. It still invokes the real `RabbitMQPublisher.connect()`, `ping()`, `publish_risk_alert()`, and `close()` methods; the assertions verify both explicit connection attempts return graceful `False`. No RabbitMQ publisher production code, message schema, exchange, queue, routing key, or retry policy changed.

Evidence with `AQUASENSE_HTTP_TEST_MODE=true` and `PYTHONDONTWRITEBYTECODE=1`, using the functional `.venv-aqs101` environment (the requested `.venv` launcher is broken because its Python 3.10 base is absent):

- offline test under a 60-second process guard: PASS; no timeout;
- `tests/test_task_be05.py`: **5/5 PASS**;
- `tests/test_aqs103_async_database_health.py`: **6/6 PASS**;
- `tests/test_aqs102_compatibility_and_routes.py`: **22/22 PASS**;
- full pytest under a 120-second process guard: **111/111 PASS, 97 warnings, 13.65s, exit 0**.

Full log: `D:\Khóa Luận\Project\shrimp-core-backend\tmp\aqs103-hang-audit-backup\full-pytest-after-rabbitmq-test-fix.log`. Remaining warnings are the pre-existing FastAPI/Starlette/asyncio deprecations and scikit-learn/XGBoost artifact compatibility warnings. No AQS-104 RabbitMQ consumer work is needed or included.

