# AQS-104 — AI Risk Event ID Contract

**Branch:** `feature/AQS-104_ai-risk-event-id` from `origin/develop@e3363ee`.
**Production approval:** unchanged — `PRODUCTION_AI_BLOCKED_PENDING_APPROVAL`.

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
