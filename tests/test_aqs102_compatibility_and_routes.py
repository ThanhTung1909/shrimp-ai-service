"""Runtime contract coverage for AQS-102 compatibility and route composition."""

import json
import math

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.schemas.prediction import NestJSPredictRequest


CANONICAL_ASSESSMENT_PATH = "/api/v1/ai/water-quality/comprehensive-assessment"
DOUBLE_PREFIX_ASSESSMENT_PATH = "/api/v1/v1/ai/water-quality/comprehensive-assessment"


def canonical_payload() -> dict[str, object]:
    return {
        "pondId": "78ad6b2a-b628-4c7f-9f2c-91953a3ea2cb",
        "temperature": 29.5,
        "ph": 7.8,
        "dissolvedOxygen": 5.2,
        "salinity": 15.0,
        "turbidity": 20.0,
    }


def legacy_payload() -> dict[str, object]:
    return {
        "pondId": "78ad6b2a-b628-4c7f-9f2c-91953a3ea2cb",
        "currentTemp": 29.5,
        "currentPH": 7.8,
        "currentDO": 5.2,
        "salinity": 15.0,
        "turbidity": 20.0,
    }


def registered_route_paths() -> list[str]:
    """Read effective paths through FastAPI 0.163's nested router composition."""
    paths: list[str] = []

    def collect(candidates) -> None:
        for candidate in candidates:
            path = getattr(candidate, "path", None)
            if path is not None:
                paths.append(path)
                continue

            nested_candidates = getattr(candidate, "effective_candidates", None)
            if callable(nested_candidates):
                collect(nested_candidates())

    collect(app.routes)
    return paths


@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_schema_normalizes_canonical_and_legacy_payloads_identically():
    canonical = NestJSPredictRequest.model_validate(canonical_payload())
    legacy = NestJSPredictRequest.model_validate(legacy_payload())

    assert canonical.model_dump() == legacy.model_dump()
    assert legacy.temperature == 29.5
    assert legacy.ph == 7.8
    assert legacy.dissolved_oxygen == 5.2


def test_schema_accepts_the_documented_minimal_legacy_payload():
    request = NestJSPredictRequest.model_validate(
        {
            "pondId": "78ad6b2a-b628-4c7f-9f2c-91953a3ea2cb",
            "currentTemp": 29.5,
            "currentPH": 7.8,
            "currentDO": 5.2,
        }
    )

    assert request.temperature == 29.5
    assert request.ph == 7.8
    assert request.dissolved_oxygen == 5.2
    assert request.salinity == 15.0
    assert request.turbidity == 25.0


def test_schema_accepts_equal_canonical_and_legacy_values():
    payload = canonical_payload() | {
        "currentTemp": 29.5,
        "currentPH": 7.8,
        "currentDO": 5.2,
    }

    request = NestJSPredictRequest.model_validate(payload)

    assert request.temperature == 29.5
    assert request.ph == 7.8
    assert request.current_do == 5.2


def test_schema_rejects_conflicting_canonical_and_legacy_values():
    payload = canonical_payload() | {"currentDO": 4.8}

    with pytest.raises(ValidationError, match="Conflicting values"):
        NestJSPredictRequest.model_validate(payload)


def test_schema_preserves_zero_from_legacy_payload():
    payload = legacy_payload() | {"currentDO": 0.0}

    request = NestJSPredictRequest.model_validate(payload)

    assert request.dissolved_oxygen == 0.0
    assert request.current_do == 0.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("currentDO", None),
        ("currentTemp", "29.5"),
        ("currentDO", math.nan),
        ("currentDO", math.inf),
        ("currentDO", 31.0),
    ],
)
def test_schema_rejects_invalid_legacy_telemetry(field, value):
    payload = legacy_payload() | {field: value}

    with pytest.raises(ValidationError):
        NestJSPredictRequest.model_validate(payload)


def test_http_accepts_canonical_and_legacy_payloads(client):
    canonical_response = client.post("/api/predict", json=canonical_payload())
    legacy_response = client.post("/api/predict", json=legacy_payload())

    assert canonical_response.status_code == 200
    assert legacy_response.status_code == 200
    for field in ("predictedDO", "predictedPH", "riskScore", "riskLevel"):
        assert canonical_response.json()[field] == legacy_response.json()[field]


def test_http_rejects_missing_required_legacy_metric(client):
    payload = legacy_payload()
    payload.pop("currentTemp")

    response = client.post("/api/predict", json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("currentDO", None),
        ("currentTemp", "29.5"),
        ("currentDO", math.nan),
        ("currentDO", math.inf),
        ("currentDO", 31.0),
    ],
)
def test_http_rejects_invalid_legacy_telemetry(client, field, value):
    payload = legacy_payload() | {field: value}
    if isinstance(value, float) and not math.isfinite(value):
        response = client.post(
            "/api/predict",
            content=json.dumps(payload, allow_nan=True),
            headers={"content-type": "application/json"},
        )
    else:
        response = client.post("/api/predict", json=payload)

    assert response.status_code == 422


def test_http_rejects_conflicting_payload(client):
    response = client.post(
        "/api/predict",
        json=canonical_payload() | {"currentDO": 4.8},
    )

    assert response.status_code == 422
    assert "Conflicting values" in response.json()["errors"][0]["message"]


def test_http_rejects_unknown_field(client):
    response = client.post(
        "/api/predict",
        json=canonical_payload() | {"unknownSensor": 1.0},
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["type"] == "extra_forbidden"


def test_openapi_and_runtime_register_only_the_canonical_assessment_route(client):
    openapi_paths = client.get("/openapi.json").json()["paths"]
    registered_paths = registered_route_paths()

    assert CANONICAL_ASSESSMENT_PATH in openapi_paths
    assert DOUBLE_PREFIX_ASSESSMENT_PATH not in openapi_paths
    assert registered_paths.count(CANONICAL_ASSESSMENT_PATH) == 1
    assert DOUBLE_PREFIX_ASSESSMENT_PATH not in registered_paths


def test_assessment_route_and_aqs101_predict_route_remain_available(client):
    assessment_response = client.post(CANONICAL_ASSESSMENT_PATH, json=canonical_payload())
    double_prefix_response = client.post(DOUBLE_PREFIX_ASSESSMENT_PATH, json=canonical_payload())
    predict_response = client.post("/api/predict", json=canonical_payload())

    assert assessment_response.status_code == 200
    assert double_prefix_response.status_code == 404
    assert predict_response.status_code == 200


def test_assessment_route_is_read_only_development_analysis(client):
    class FailOnRedisWrite:
        async def set_water_quality_forecast(self, *args, **kwargs):
            raise AssertionError("assessment route must not write Redis")

    class FailOnAlertPublish:
        async def publish_risk_alert(self, *args, **kwargs):
            raise AssertionError("assessment route must not publish RabbitMQ alerts")

    with TestClient(app, raise_server_exceptions=False) as isolated_client:
        original_redis = app.state.redis_service
        original_rabbitmq = app.state.rabbitmq_publisher
        app.state.redis_service = FailOnRedisWrite()
        app.state.rabbitmq_publisher = FailOnAlertPublish()
        try:
            response = isolated_client.post(CANONICAL_ASSESSMENT_PATH, json=canonical_payload())
        finally:
            app.state.redis_service = original_redis
            app.state.rabbitmq_publisher = original_rabbitmq

    assert response.status_code == 200
    assert response.json()["pond_id"] == canonical_payload()["pondId"]
