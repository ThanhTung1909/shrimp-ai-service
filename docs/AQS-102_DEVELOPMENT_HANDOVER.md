# AQS-102 Development Handover

## Three-repository audit, regression and publication verification — 2026-11-20

**Result:** `AQUASENSE_THREE_REPOSITORIES_PUSH_VERIFIED`. The FastAPI source/routing baseline was already published on `feature/AQS-102_dual-compatibility-route-prefix` at `a9c1b44450964f9c95f40b70727b6434ac7b1861`; its source did not require another implementation commit. The separately published Core target remains `2f0d9f26b9b24890a316db3e41b43539dbf0b593`. Frontend `main` advanced from `957160f8a197dfc61ab90a8dead226a16619ca95` to `2313ca4255e33207fbb66503523f684ce543e14a` with `fix(aqs-101): harden pond prediction UX` (21 audited files, including its acceptance tests); it continues to call Core API endpoints rather than FastAPI directly.

- FastAPI full regression was rerun with isolated `TEMP`/`TMP` and `--basetemp`: **105/105 PASS** (80 warnings; dependency deprecations and the pre-existing feeding scaler/XGBoost serialization-version warnings remain visible).
- Direct loopback HTTP acceptance in `AQUASENSE_HTTP_TEST_MODE=true` passed: `/health` 200; `/api/predict` canonical, legacy and equal mixed inputs 200; conflict and invalid-string payloads 422; canonical comprehensive-assessment 200; doubled `/api/v1/v1/...` route 404. The temporary Uvicorn process was stopped after the check.
- Current Core evidence: focused regression **79/79**, real Core-to-FastAPI transport **2/2**, build PASS, lint PASS with 19 existing warnings, and owned loopback/tmpfs PostgreSQL E2E **16/16** with fixture database/container/port cleanup.
- Current Frontend evidence: production build PASS, lint PASS with **0 errors / 137 warnings**, and Playwright **15/15 PASS**. `test-results/.last-run.json` was intentionally kept local and not committed.
- GitHub Actions was queried read-only for the three target SHAs; no matching workflow run was returned. This is recorded as **CI/CD: no run found**, not as a CI pass.

All pushes were non-force and remote SHA equality was verified. No production service, model, risk rule, database, deployment, or production-inference approval changed. **`PRODUCTION_AI_BLOCKED_PENDING_APPROVAL` remains controlling.**

## Final cross-service regression reconciliation — 2026-11-20

**Result:** `AQS101_AQS102_FULL_REGRESSION_PASS`; **FastAPI full regression:** **105/105 PASS**. This supplements the historical account below without changing its production governance boundary: model/risk-rule approval remains **`BLOCKED / PENDING_APPROVAL`**.

### Test lifecycle isolation

`AQUASENSE_HTTP_TEST_MODE=true` is an explicit opt-in available only to test processes. It replaces Redis and RabbitMQ collaborators with in-memory/no-op adapters and bypasses only the health endpoint's database probe. Normal application startup retains the original external collaborators. Dedicated tests replace the real Redis ping, RabbitMQ connect and database health check with failures, then prove that `TestClient` startup, `/health`, and `/api/predict` remain successful; this demonstrates that the test lifecycle makes no external connection attempt.

### Current assessment-route policy

The canonical `POST /api/v1/ai/water-quality/comprehensive-assessment` route is mounted once (no `/api/v1/v1` duplicate), accepts the normalized compatibility payload, and returns **HTTP 200** for valid input. It is a deterministic, read-only development analysis: it does not write cache or publish an alert, is not called by the Core operational prediction flow, and is not a production model/risk-rule approval. A focused test makes cache writes or alert publishing fail if they occur.

The earlier `503 RISK_RULES_PENDING_APPROVAL` statement in historical AQS-102 records does not describe the current route revision. The relevant safety control remains at Core: the normal false approval flag makes no FastAPI request and persists `HEURISTIC_RULE` fallback. An independent loopback Uvicorn process was used to verify that real Core-to-FastAPI HTTP transport **2/2 PASS** without touching external services.

**Date:** 2026-11-20
**Published branch:** `feature/AQS-102_dual-compatibility-route-prefix` at `d0904933441e2712e4ad4ecf71f4a8651217c628` (based on `origin/develop` at `e3363ee20169d54d558ede1b0c954466c10e5428`)
**Development acceptance:** `AQS-102_DEVELOPMENT_ACCEPTANCE_FULL`
**Production AI/risk-rule approval:** unchanged — `BLOCKED / PENDING_APPROVAL`

## Scope and baseline evidence

This handover records only the FastAPI compatibility and route-composition work in AQS-102. It is published on the required target branch. No model, risk rule, approval setting, database, service process, or deployment was changed.

The source contract on the actual `origin/develop` baseline used canonical input fields `temperature`, `ph`, and `dissolvedOxygen`. Before this change, a legacy payload using `currentTemp`, `currentPH`, and `currentDO` returned HTTP 422 because those required canonical values were absent. The assessment router was also mounted both directly at `/api` and through the `/api/v1` aggregate router, exposing the erroneous `/api/v1/v1/ai/water-quality/comprehensive-assessment` path.

## Implemented contract

`NestJSPredictRequest` now normalizes the following legacy aliases at one schema boundary:

| Metric | Canonical field | Accepted legacy field |
| --- | --- | --- |
| Temperature | `temperature` | `currentTemp` |
| pH | `ph` | `currentPH` |
| Dissolved oxygen | `dissolvedOxygen` | `currentDO` |

The existing input spellings `dissolved_oxygen` and `do` remain supported for compatibility. If more than one spelling for one metric is provided, the values must be equal; a conflict is rejected with HTTP 422. A value of zero is retained as a real reading. The schema rejects missing required metrics, `null`, strings, booleans, non-finite JSON numbers, out-of-range values, and unknown fields with HTTP 422. No default dissolved-oxygen reading is invented.

The predictions router is mounted exactly once, directly under `/api`. The resulting routes are:

- `POST /api/predict` — preserved for AQS-101 compatibility.
- `POST /api/v1/ai/water-quality/comprehensive-assessment` — canonical assessment route.
- `/api/v1/v1/ai/water-quality/comprehensive-assessment` — absent (HTTP 404).

The OpenAPI document exposes the canonical assessment path once and does not expose the doubled-prefix path.

## Verification

| Gate | Result |
| --- | --- |
| Baseline contract diagnosis | Reproduced legacy HTTP 422 and doubled-prefix registration on `origin/develop` |
| Schema and HTTP AQS-102 regression | 21 tests included in the full run |
| Targeted compatibility plus existing prediction tests | `39 passed, 15 warnings in 4.43s` |
| Full FastAPI regression | `103 passed, 0 failures, 0 errors, 0 skipped in 16.913s` |
| `git diff --check` | PASS |
| AQS-101 `/api/predict` availability | PASS (canonical payload returns HTTP 200) |

The remaining warnings are pre-existing dependency/model-artifact compatibility warnings, including a scikit-learn `StandardScaler` version mismatch. They were neither suppressed nor changed here.

## Approval and repository boundaries

This change does not approve or activate production AI inference, models, or risk rules. The absence of a production-approval response in this baseline source is not reclassified by AQS-102; business assessment and production activation remain blocked pending the appropriate approval.

Repository history and Core documentation reference an earlier AQS-102 commit/branch that is not present in the fetched remote branch inventory for this working branch. This implementation and its evidence are therefore tied to the actual `origin/develop` baseline recorded above.

No commit, push, merge, staging operation, or external service/database change was performed. The unrelated pre-existing stashes remain preserved.
