"""AQS-101 contract boundary tests for the Core -> FastAPI adapter."""

import pytest
from pydantic import ValidationError

from app.schemas.prediction import NestJSPredictRequest


def test_ai_develop_v1_payload_is_accepted_without_compatibility_keys():
    request = NestJSPredictRequest.model_validate(
        {
            "pondId": "78ad6b2a-b628-4c7f-9f2c-91953a3ea2cb",
            "temperature": 28.5,
            "ph": 7.7,
            "dissolvedOxygen": 5.2,
            "salinity": 15.0,
            "turbidity": 20.0,
            "timestamp": "2026-11-19T00:00:00.000Z",
        }
    )

    assert request.temperature == 28.5
    assert request.ph == 7.7
    assert request.dissolved_oxygen == 5.2


@pytest.mark.parametrize(
    "payload",
    [
        {
            "pondId": "78ad6b2a-b628-4c7f-9f2c-91953a3ea2cb",
            "temperature": 28.5,
            "ph": 7.7,
            "salinity": 15.0,
            "turbidity": 20.0,
        },
        {
            "pondId": "78ad6b2a-b628-4c7f-9f2c-91953a3ea2cb",
            "currentDO": 5.2,
            "currentPH": 7.7,
            "currentTemp": 28.5,
            "salinity": 15.0,
            "turbidity": 20.0,
        },
    ],
)
def test_missing_or_legacy_telemetry_keys_are_rejected(payload):
    with pytest.raises(ValidationError):
        NestJSPredictRequest.model_validate(payload)
