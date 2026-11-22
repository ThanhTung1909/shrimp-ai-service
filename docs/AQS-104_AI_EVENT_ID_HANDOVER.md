# AQS-104 — AI Risk Event ID Contract

**Branch:** `feature/AQS-104_ai-risk-event-id` from `origin/develop@e3363ee`.
**Production approval:** unchanged — `PRODUCTION_AI_BLOCKED_PENDING_APPROVAL`.

## Autonomous closeout verification — 2026-11-22

The robust-connect timeout remediation was revalidated without a broker:
`tests/test_task_be05.py` plus `tests/test_aqs104_ai_event_id.py` passed
**13/13** in 18.39s, and the full suite passed **90/90** in 18.25s using the
working `.venv-aqs101`. Existing dependency/model-serialization warnings
remain. Docker config/engine access is still denied, so no RabbitMQ or
PostgreSQL fixture was inspected or changed and no cross-service rerun is
claimed. Production approval remains unchanged.

## Offline-timeout remediation — 2026-11-21

### Root cause and decision

`aio_pika.connect_robust(..., timeout=2.0)` applies its timeout to individual
connection work, but its robust connection factory retries an observed
`TimeoutError` after its reconnect interval. It therefore did not bound the
whole awaited `connect_robust()` call. `fail_fast=True` was not a remedy: it is
already the library default and this error path remained retryable.

`RabbitMQPublisher` now owns a single shared in-flight connect task protected
by a lock. An application-level `asyncio.wait_for(asyncio.shield(...))`
enforces the configured two-second deadline across robust connect, channel and
topology setup. On timeout, it cancels *and awaits* that task; partial channel
and connection resources are closed in `_connect_once`'s `finally` block.
Concurrent callers share the same attempt, preventing reconnect-task buildup.
The AMQP URL is rendered without credentials in logs. A later call creates a
new attempt, preserving recovery when the broker becomes available.

### Evidence

- Syntax compilation: PASS.
- Publisher/event-ID regression: **13/13 PASS, 18.44s**. Coverage includes
  refused and nonresponsive broker, timeout cancellation, partial-resource
  cleanup, five concurrent connects sharing one attempt, offline publish and
  recovery after failure.
- AI full regression: **90/90 PASS, 17.54s** with `.venv-aqs101` (the requested
  `.venv` has no executable Python base). Warnings are existing dependency or
  serialized-model compatibility warnings.
- AQS-102 integration: a dedicated no-commit temporary worktree merged cleanly
  with `feature/AQS-102_dual-compatibility-route-prefix@991bbf3`; the combined
  AQS-102/AQS-104 focused suite passed **35/35, 8.87s**.

Docker's named-pipe API was denied in this session, so the AQS-104-labelled
RabbitMQ/PostgreSQL containers could not be revalidated safely and no broker,
database, DLQ, frontend or provider E2E action was attempted. This update does
not change production approval, send Email/SMS/FCM, or claim production success.

## Change

`RabbitMQPublisher.publish_risk_alert()` now creates UUIDv4 `event_id` for a new business publish operation and adds it to the existing `ai.risk.detected` payload. A caller retrying a previously created operation supplies its original `event_id`; it is validated and retained rather than regenerated. Two independent calls receive different IDs.

The RabbitMQ topology is unchanged: exchange `shrimp.events`, queue `ai_risk_alerts`, routing key `ai.risk.detected`. Existing endpoint risk labels are normalized at the event boundary: `CRITICAL`/`DANGER → HIGH` and `WARNING → MEDIUM`, so the Core AQS-104 consumer receives its documented `LOW|MEDIUM|HIGH` contract without changing prediction scoring.

## Tests

- New `tests/test_aqs104_ai_event_id.py`: UUID creation, payload inclusion, explicit-retry stability, independent-ID distinction, invalid-ID rejection.
- Updated `tests/test_task_be05.py`: validates normalized contract risk level in publisher/feeding/prediction flows.
- Targeted publisher/event-ID suite: **8/8 PASS**.
- Full FastAPI pytest: **85/85 PASS, 95 warnings, 17.10s** using `.venv-aqs101` with isolated HTTP mode.

## Contract and limits

This provides an idempotency key for backend durable inbox processing but does not claim exactly-once message delivery. Retrying the same business operation requires its caller to retain and reuse the returned/generated ID; a new HTTP request remains a separate business operation unless a higher-level stable request ID is introduced.

RabbitMQ/PostgreSQL end-to-end remains blocked by the unavailable dedicated Docker fixture; no real broker, database, migration, notification provider or production approval was used or changed.
