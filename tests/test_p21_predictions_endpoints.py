"""
Unit & Integration Tests cho P2-1:
- POST /api/predict/water-quality & POST /api/v1/predict/water-quality
- POST /api/predict/disease-risk & POST /api/v1/predict/disease-risk
- Các hàm mô hình khoa học forecast_water_quality_trajectory và assess_disease_risk
- Kiểm thử Redis caching (optional, graceful degradation) và không phát RabbitMQ alert
"""

from datetime import datetime, timedelta, timezone
import time
from typing import Any, Dict, List, Optional
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.disease_risk import (
    assess_disease_risk,
    forecast_water_quality_trajectory,
)
from app.services.rabbitmq_publisher import RabbitMQPublisher
from app.services.redis_cache import (
    DISEASE_CACHE_PREFIX,
    WATER_TRAJECTORY_CACHE_PREFIX,
    RedisCacheService,
)

VALID_POND_UUID = "550e8400-e29b-41d4-a716-446655440000"


class MockRedisClient:
    def __init__(self):
        self.store: Dict[str, str] = {}
        self.ttls: Dict[str, int] = {}

    async def ping(self) -> bool:
        return True

    async def get(self, key: str) -> Optional[str]:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def aclose(self) -> None:
        pass


class SpyRabbitMQExchange:
    def __init__(self):
        self.published: List[Dict[str, Any]] = []

    async def publish(self, message: Any, routing_key: str):
        self.published.append({"routing_key": routing_key})


class SpyRabbitMQChannel:
    def __init__(self, exchange: SpyRabbitMQExchange):
        self.exchange = exchange

    async def declare_exchange(self, name: str, type: Any, durable: bool):
        return self.exchange

    async def declare_queue(self, name: str, durable: bool):
        class _Q:
            async def bind(self, exchange, routing_key):
                pass
        return _Q()

    async def close(self):
        pass


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def _base_water_quality_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "pondId": VALID_POND_UUID,
        "horizonHours": 24,
        "stepHours": 1,
        "timestamp": "2026-11-22T11:00:00Z",  # 18:00 giờ Việt Nam (UTC+7)
        "currentMetrics": {
            "currentDO": 6.2,
            "currentPH": 7.8,
            "currentTemp": 29.0,
            "salinity": 15.0,
            "turbidity": 25.0,
        },
        "recentHistory": [],
        "pondProfile": {
            "areaM2": 2000.0,
            "depthM": 1.4,
            "shrimpDensity": 100.0,
        },
    }
    payload.update(overrides)
    return payload


def _assert_water_trajectory_shape_and_bounds(data: Dict[str, Any], expected_horizon: int, expected_step: int):
    expected_top_keys = {
        "pondId",
        "horizonHours",
        "stepHours",
        "overallRiskScore",
        "overallRiskLevel",
        "series",
        "factors",
        "recommendations",
        "latencyMs",
        "timestamp",
    }
    assert expected_top_keys.issubset(data.keys())
    assert data["pondId"] == VALID_POND_UUID
    assert data["horizonHours"] == expected_horizon
    assert data["stepHours"] == expected_step
    assert 0.0 <= data["overallRiskScore"] <= 100.0
    assert data["overallRiskLevel"] in {"SAFE", "WARNING", "DANGER"}
    assert data["latencyMs"] < 500.0
    assert isinstance(data["factors"], list) and len(data["factors"]) == len(dict.fromkeys(data["factors"]))
    assert isinstance(data["recommendations"], list) and len(data["recommendations"]) == len(
        dict.fromkeys(data["recommendations"])
    )

    series = data["series"]
    assert len(series) >= 1
    assert series[-1]["offsetHours"] == expected_horizon

    prev_offset = 0
    for pt in series:
        assert set(pt.keys()) == {
            "offsetHours",
            "predictedTime",
            "predictedDO",
            "predictedPH",
            "predictedTemperature",
            "riskScore",
            "riskLevel",
        }
        assert pt["offsetHours"] > prev_offset
        prev_offset = pt["offsetHours"]

        dt = datetime.fromisoformat(pt["predictedTime"].replace("Z", "+00:00"))
        assert dt.tzinfo is not None

        assert 0.5 <= pt["predictedDO"] <= 18.0
        assert 5.5 <= pt["predictedPH"] <= 10.0
        assert 15.0 <= pt["predictedTemperature"] <= 42.0
        assert 0.0 <= pt["riskScore"] <= 100.0
        assert pt["riskLevel"] in {"SAFE", "WARNING", "DANGER"}

        if pt["riskScore"] >= 65.0:
            assert pt["riskLevel"] == "DANGER"
        elif pt["riskScore"] >= 35.0:
            assert pt["riskLevel"] == "WARNING"
        else:
            assert pt["riskLevel"] == "SAFE"

    assert data["overallRiskScore"] == max(pt["riskScore"] for pt in series)


# ==============================================================================
# 1. Water Quality Trajectory Tests (12h, 24h, stepHours=1/2, parity, bounds)
# ==============================================================================


def test_water_quality_trajectory_24h_step1_and_latency(client):
    payload = _base_water_quality_payload(horizonHours=24, stepHours=1)
    t0 = time.perf_counter()
    resp = client.post("/api/predict/water-quality", json=payload)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert resp.status_code == 200, resp.text
    assert elapsed_ms < 500.0
    data = resp.json()
    _assert_water_trajectory_shape_and_bounds(data, expected_horizon=24, expected_step=1)
    assert len(data["series"]) == 24
    assert [p["offsetHours"] for p in data["series"]] == list(range(1, 25))


def test_water_quality_trajectory_12h_step2(client):
    payload = _base_water_quality_payload(horizonHours=12, stepHours=2)
    resp = client.post("/api/predict/water-quality", json=payload)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    _assert_water_trajectory_shape_and_bounds(data, expected_horizon=12, expected_step=2)
    assert len(data["series"]) == 6
    assert [p["offsetHours"] for p in data["series"]] == [2, 4, 6, 8, 10, 12]


def test_water_quality_trajectory_non_divisible_horizon_ends_at_horizon(client):
    payload = _base_water_quality_payload(horizonHours=13, stepHours=2)
    resp = client.post("/api/predict/water-quality", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    _assert_water_trajectory_shape_and_bounds(data, expected_horizon=13, expected_step=2)
    assert [p["offsetHours"] for p in data["series"]] == [2, 4, 6, 8, 10, 12, 13]


def test_water_quality_v1_route_parity_and_snake_case(client):
    camel_payload = _base_water_quality_payload(horizonHours=12, stepHours=2)
    snake_payload = {
        "pond_id": VALID_POND_UUID,
        "horizon_hours": 12,
        "step_hours": 2,
        "timestamp": "2026-11-22T11:00:00Z",
        "current_metrics": {
            "current_do": 6.2,
            "current_ph": 7.8,
            "current_temp": 29.0,
            "salinity": 15.0,
            "turbidity": 25.0,
        },
        "recent_history": [],
        "pond_profile": {
            "area_m2": 2000.0,
            "depth_m": 1.4,
            "shrimp_density": 100.0,
        },
    }

    r_direct = client.post("/api/predict/water-quality", json=camel_payload)
    r_v1 = client.post("/api/v1/predict/water-quality", json=snake_payload)
    assert r_direct.status_code == 200
    assert r_v1.status_code == 200

    d1, d2 = r_direct.json(), r_v1.json()
    assert d1["overallRiskScore"] == d2["overallRiskScore"]
    assert d1["overallRiskLevel"] == d2["overallRiskLevel"]
    assert d1["series"] == d2["series"]


def test_water_quality_diurnal_history_drift_and_density_effects():
    base_ts = datetime(2026, 11, 22, 11, 0, 0, tzinfo=timezone.utc)  # 18:00 UTC+7 (hoàng hôn)
    baseline = forecast_water_quality_trajectory(
        base_timestamp=base_ts,
        horizon_hours=12,
        step_hours=1,
        current_do=5.5,
        current_ph=7.9,
        current_temp=29.0,
        salinity=15.0,
        turbidity=30.0,
        recent_history=[],
        shrimp_density=100.0,
    )
    high_density = forecast_water_quality_trajectory(
        base_timestamp=base_ts,
        horizon_hours=12,
        step_hours=1,
        current_do=5.5,
        current_ph=7.9,
        current_temp=29.0,
        salinity=15.0,
        turbidity=30.0,
        recent_history=[
            {
                "recordedAt": (base_ts - timedelta(hours=3)).isoformat(),
                "dissolvedOxygen": 6.4,
                "ph": 8.1,
                "temperature": 29.6,
            },
            {
                "recordedAt": (base_ts - timedelta(hours=1)).isoformat(),
                "dissolvedOxygen": 5.8,
                "ph": 8.0,
                "temperature": 29.2,
            },
        ],
        shrimp_density=240.0,
    )

    # Đêm -> DO giảm dần và mật độ cao + xu hướng giảm khiến DO thấp hơn rõ rệt
    assert baseline["series"][5]["predictedDO"] < 5.5
    assert high_density["series"][-1]["predictedDO"] < baseline["series"][-1]["predictedDO"]
    assert high_density["overallRiskScore"] >= baseline["overallRiskScore"]


# ==============================================================================
# 2. Validation Tests (HTTP 422)
# ==============================================================================


@pytest.mark.parametrize(
    "invalid_override",
    [
        {"horizonHours": 11},
        {"horizonHours": 25},
        {"horizonHours": True},
        {"stepHours": 5},
        {"stepHours": 0},
        {"stepHours": True},
        {"pondId": "pond-01"},
        {"pondId": "550e8400e29b41d4a716446655440000"},  # thiếu dấu gạch ngang
        {"timestamp": "2026-11-22T09:00:00"},  # naive timestamp
        {"timestamp": "2026-11-22"},  # date-only naive
        {"timestamp": "not-a-timestamp"},
    ],
)
def test_water_quality_invalid_inputs_return_422(client, invalid_override):
    payload = _base_water_quality_payload(**invalid_override)
    resp = client.post("/api/predict/water-quality", json=payload)
    assert resp.status_code == 422, f"Expected 422 for {invalid_override}, got {resp.status_code}: {resp.text}"


@pytest.mark.parametrize(
    "raw_body",
    [
        '{"pondId": "550e8400-e29b-41d4-a716-446655440000", "currentMetrics": {"currentDO": NaN, "currentPH": 7.8, "currentTemp": 28.5}}',
        '{"pondId": "550e8400-e29b-41d4-a716-446655440000", "currentMetrics": {"currentDO": 5.5, "currentPH": Infinity, "currentTemp": 28.5}}',
        '{"pondId": "550e8400-e29b-41d4-a716-446655440000", "currentMetrics": {"currentDO": 5.5, "currentPH": 7.8, "currentTemp": -Infinity}}',
    ],
)
def test_water_quality_nan_inf_returns_422(client, raw_body):
    resp = client.post(
        "/api/predict/water-quality",
        content=raw_body,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize(
    "invalid_metrics",
    [
        {"currentDO": -0.1, "currentPH": 7.8, "currentTemp": 28.0},
        {"currentDO": 26.0, "currentPH": 7.8, "currentTemp": 28.0},
        {"currentDO": 6.0, "currentPH": 3.5, "currentTemp": 28.0},
        {"currentDO": 6.0, "currentPH": 7.8, "currentTemp": 50.0},
    ],
)
def test_water_quality_metric_bounds_return_422(client, invalid_metrics):
    payload = _base_water_quality_payload(currentMetrics=invalid_metrics)
    resp = client.post("/api/predict/water-quality", json=payload)
    assert resp.status_code == 422


@pytest.mark.parametrize(
    "raw_body",
    [
        '{"pondId": "550e8400-e29b-41d4-a716-446655440000", "currentMetrics": {"currentDO": NaN, "currentPH": 7.8, "currentTemp": 28.5}}',
        '{"pondId": "not-uuid", "currentMetrics": {"currentDO": 6.0, "currentPH": 7.8, "currentTemp": 28.5}}',
        '{"pondId": "550e8400-e29b-41d4-a716-446655440000", "timestamp": "2026-11-22T09:00:00", "currentMetrics": {"currentDO": 6.0, "currentPH": 7.8, "currentTemp": 28.5}}',
    ],
)
def test_disease_risk_invalid_inputs_return_422(client, raw_body):
    resp = client.post(
        "/api/predict/disease-risk",
        content=raw_body,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422, resp.text


# ==============================================================================
# 3. Disease Risk Assessment Tests (WSSV, AHPND/EMS, Healthy, v1 Parity)
# ==============================================================================


def _assert_disease_response_shape(data: Dict[str, Any]):
    assert {
        "pondId",
        "overallRiskScore",
        "overallRiskLevel",
        "diseases",
        "recommendations",
        "latencyMs",
        "timestamp",
    }.issubset(data.keys())
    assert data["pondId"] == VALID_POND_UUID
    assert 5.0 <= data["overallRiskScore"] <= 100.0
    assert data["overallRiskLevel"] in {"SAFE", "WARNING", "DANGER"}
    assert data["latencyMs"] < 500.0
    assert isinstance(data["recommendations"], list)

    diseases = {d["code"]: d for d in data["diseases"]}
    assert set(diseases.keys()) == {"WSSV", "AHPND_EMS"}
    assert diseases["WSSV"]["name"] == "Bệnh Đốm trắng (WSSV)"
    assert diseases["AHPND_EMS"]["name"] == "Bệnh Hoại tử gan tụy cấp (AHPND/EMS)"

    for d in diseases.values():
        assert set(d.keys()) == {
            "code",
            "name",
            "riskScore",
            "riskLevel",
            "indicators",
            "recommendations",
        }
        assert 5.0 <= d["riskScore"] <= 100.0
        assert d["riskLevel"] in {"SAFE", "WARNING", "DANGER"}
        assert isinstance(d["indicators"], list) and len(d["indicators"]) >= 1
        assert isinstance(d["recommendations"], list) and len(d["recommendations"]) >= 1

        if d["riskScore"] >= 70.0:
            assert d["riskLevel"] == "DANGER"
        elif d["riskScore"] >= 40.0:
            assert d["riskLevel"] == "WARNING"
        else:
            assert d["riskLevel"] == "SAFE"

    assert data["overallRiskScore"] == max(d["riskScore"] for d in diseases.values())


def test_disease_risk_high_wssv_scenario(client):
    """Kịch bản nguy cơ cao WSSV: nước lạnh + sốc nhiệt ΔT + biến động ΔpH"""
    payload = {
        "pondId": VALID_POND_UUID,
        "timestamp": "2026-11-22T09:00:00+07:00",
        "currentMetrics": {
            "currentDO": 5.4,
            "currentPH": 7.6,
            "currentTemp": 24.2,
            "salinity": 4.5,
            "turbidity": 25.0,
            "nh3": 0.008,
            "no2": 0.2,
        },
        "variability24h": {
            "temperatureDelta": 3.8,
            "phDelta": 0.85,
            "minDO": 4.2,
            "minTemp": 23.8,
            "maxTemp": 27.6,
        },
        "pondProfile": {
            "shrimpDensity": 180.0,
            "daysOfCulture": 55,
        },
    }

    resp = client.post("/api/predict/disease-risk", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    _assert_disease_response_shape(data)

    wssv = next(d for d in data["diseases"] if d["code"] == "WSSV")
    assert wssv["riskLevel"] == "DANGER"
    assert wssv["riskScore"] >= 70.0
    assert data["overallRiskLevel"] == "DANGER"
    assert data["overallRiskScore"] == wssv["riskScore"]


def test_disease_risk_high_ahpnd_ems_scenario(client):
    """Kịch bản nguy cơ cao AHPND/EMS: nước ấm + mặn cao + pH kiềm + NH3 cao + DOC 10-45"""
    payload = {
        "pondId": VALID_POND_UUID,
        "timestamp": "2026-11-22T07:00:00Z",
        "currentMetrics": {
            "currentDO": 4.8,
            "currentPH": 8.6,
            "currentTemp": 32.8,
            "salinity": 26.0,
            "turbidity": 68.0,
            "nh3": 0.065,
            "no2": 2.4,
        },
        "variability24h": {
            "temperatureDelta": 1.2,
            "phDelta": 0.3,
            "minDO": 4.1,
        },
        "pondProfile": {
            "shrimpDensity": 120.0,
            "daysOfCulture": 28,
        },
    }

    resp = client.post("/api/predict/disease-risk", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    _assert_disease_response_shape(data)

    ahpnd = next(d for d in data["diseases"] if d["code"] == "AHPND_EMS")
    assert ahpnd["riskLevel"] == "DANGER"
    assert ahpnd["riskScore"] >= 70.0
    assert data["overallRiskLevel"] == "DANGER"

    # Kiểm tra parity với /api/v1/predict/disease-risk
    resp_v1 = client.post("/api/v1/predict/disease-risk", json=payload)
    assert resp_v1.status_code == 200
    d_v1 = resp_v1.json()
    assert d_v1["overallRiskScore"] == data["overallRiskScore"]
    assert d_v1["diseases"] == data["diseases"]


def test_disease_risk_healthy_pond_both_safe(client):
    """Kịch bản ao khỏe mạnh: cả WSSV và AHPND/EMS đều SAFE"""
    payload = {
        "pondId": VALID_POND_UUID,
        "currentMetrics": {
            "currentDO": 6.4,
            "currentPH": 7.8,
            "currentTemp": 29.0,
            "salinity": 15.0,
            "turbidity": 28.0,
            "nh3": 0.005,
            "no2": 0.1,
        },
        "variability24h": {
            "temperatureDelta": 0.8,
            "phDelta": 0.25,
            "minDO": 5.3,
            "minTemp": 28.4,
            "maxTemp": 29.2,
        },
        "pondProfile": {
            "shrimpDensity": 100.0,
            "daysOfCulture": 60,
        },
    }

    resp = client.post("/api/predict/disease-risk", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    _assert_disease_response_shape(data)

    for d in data["diseases"]:
        assert d["riskLevel"] == "SAFE"
        assert 5.0 <= d["riskScore"] < 40.0
    assert data["overallRiskLevel"] == "SAFE"


def test_disease_risk_direct_function_clamps_minimum_and_maximum():
    healthy = assess_disease_risk(current_do=6.5, current_ph=7.8, current_temp=29.0)
    assert all(d["riskScore"] == 5.0 for d in healthy["diseases"])
    assert healthy["overallRiskLevel"] == "SAFE"

    extreme = assess_disease_risk(
        current_do=2.0,
        current_ph=9.3,
        current_temp=34.5,
        salinity=30.0,
        turbidity=95.0,
        nh3=0.12,
        no2=8.0,
        min_do=1.8,
        days_of_culture=25,
    )
    ahpnd = next(d for d in extreme["diseases"] if d["code"] == "AHPND_EMS")
    assert ahpnd["riskScore"] == 100.0
    assert ahpnd["riskLevel"] == "DANGER"


# ==============================================================================
# 4. Redis Optional Caching, Graceful Degradation & No RabbitMQ Side Effects
# ==============================================================================


@pytest.mark.anyio
async def test_redis_disease_and_trajectory_cache_helpers_and_offline_degradation():
    mock_client = MockRedisClient()
    svc = RedisCacheService(client=mock_client)

    assert svc.make_disease_key("pond-1") == f"{DISEASE_CACHE_PREFIX}:pond-1"
    assert svc.make_water_trajectory_key("pond-1") == f"{WATER_TRAJECTORY_CACHE_PREFIX}:pond-1"

    assert await svc.set_disease_risk_forecast("pond-1", {"overallRiskScore": 25.0}) is True
    assert (await svc.get_disease_risk_forecast("pond-1"))["overallRiskScore"] == 25.0

    assert await svc.set_water_quality_trajectory("pond-1", {"overallRiskScore": 12.0}) is True
    assert (await svc.get_water_quality_trajectory("pond-1"))["overallRiskScore"] == 12.0

    offline_svc = RedisCacheService(redis_url="redis://localhost:9999/0")
    assert await offline_svc.set_disease_risk_forecast("pond-1", {"x": 1}) is False
    assert await offline_svc.get_disease_risk_forecast("pond-1") is None
    await offline_svc.close()


def test_new_endpoints_cache_without_publishing_rabbitmq(client):
    prev_redis = getattr(app.state, "redis_service", None)
    prev_rmq = getattr(app.state, "rabbitmq_publisher", None)

    mock_redis = MockRedisClient()
    app.state.redis_service = RedisCacheService(client=mock_redis)

    spy_exchange = SpyRabbitMQExchange()
    app.state.rabbitmq_publisher = RabbitMQPublisher(
        channel=SpyRabbitMQChannel(spy_exchange),
        exchange=spy_exchange,
    )

    try:
        # Cả 2 endpoint gặp điều kiện DANGER nhưng tuyệt đối không được phát sự kiện RabbitMQ
        water_payload = _base_water_quality_payload(
            currentMetrics={
                "currentDO": 2.5,
                "currentPH": 6.2,
                "currentTemp": 34.0,
                "salinity": 15.0,
                "turbidity": 85.0,
            }
        )
        r_water = client.post("/api/predict/water-quality", json=water_payload)
        assert r_water.status_code == 200
        assert r_water.json()["overallRiskLevel"] == "DANGER"

        disease_payload = {
            "pondId": VALID_POND_UUID,
            "currentMetrics": {
                "currentDO": 2.5,
                "currentPH": 8.8,
                "currentTemp": 24.0,
                "salinity": 26.0,
                "turbidity": 75.0,
                "nh3": 0.08,
                "no2": 6.0,
            },
            "variability24h": {"temperatureDelta": 4.0, "phDelta": 0.9, "minDO": 2.4},
            "pondProfile": {"shrimpDensity": 200.0, "daysOfCulture": 25},
        }
        r_disease = client.post("/api/predict/disease-risk", json=disease_payload)
        assert r_disease.status_code == 200
        assert r_disease.json()["overallRiskLevel"] == "DANGER"

        # Kiểm tra đã lưu cache Redis đúng key và không publish RabbitMQ
        assert f"{WATER_TRAJECTORY_CACHE_PREFIX}:{VALID_POND_UUID}" in mock_redis.store
        assert f"{DISEASE_CACHE_PREFIX}:{VALID_POND_UUID}" in mock_redis.store
        assert len(spy_exchange.published) == 0
    finally:
        app.state.redis_service = prev_redis
        app.state.rabbitmq_publisher = prev_rmq
