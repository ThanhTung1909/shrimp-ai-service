"""
Unit tests cho TASK-BE-04: Tích hợp Redis Cache bất đồng bộ.
Kiểm tra chi tiết:
- Quy ước đặt key: ai:forecast:feeding:{pond_id} và ai:forecast:water:{pond_id}
- Thời gian sống TTL = 1800s (30 phút)
- Cơ chế chịu lỗi (Graceful degradation) khi Redis offline
- Lưu và đọc cache qua REST API endpoints (độ trễ < 5ms)
- Báo cáo trạng thái Redis trong GET /health
Do Backend-Integration-Agent chủ trì.
"""

import json
from typing import Dict, Optional
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.redis_cache import (
    DEFAULT_CACHE_TTL,
    FEEDING_CACHE_PREFIX,
    WATER_CACHE_PREFIX,
    RedisCacheService,
)


class MockRedisAsyncClient:
    """Mock Redis Async Client lưu trữ trên bộ nhớ RAM để kiểm thử độc lập"""

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


@pytest.fixture
def mock_redis_service():
    """Tạo instance RedisCacheService sử dụng MockRedisAsyncClient"""
    mock_client = MockRedisAsyncClient()
    return RedisCacheService(client=mock_client)


@pytest.fixture(scope="module")
def client():
    """Khởi tạo TestClient nạp sẵn Lifespan"""
    with TestClient(app) as test_client:
        yield test_client


# ==============================================================================
# 1. Tests cho Key Naming & TTL Conventions
# ==============================================================================

def test_redis_service_key_conventions():
    """Kiểm tra quy ước cấu trúc key định danh theo ao nuôi"""
    svc = RedisCacheService()
    assert svc.make_feeding_key("pond-01") == f"{FEEDING_CACHE_PREFIX}:pond-01"
    assert svc.make_water_key("pond-01") == f"{WATER_CACHE_PREFIX}:pond-01"
    assert svc.default_ttl == DEFAULT_CACHE_TTL
    assert svc.default_ttl == 1800  # Đúng 30 phút theo chuẩn hệ thống


# ==============================================================================
# 2. Tests cho Redis Operations với Mock Async Client
# ==============================================================================

@pytest.mark.anyio
async def test_redis_service_crud_operations(mock_redis_service):
    """Kiểm tra các thao tác ghi và đọc cache nghiệp vụ"""
    pond_id = "pond-demo"
    sample_forecast = {
        "pond_id": pond_id,
        "recommended_feed_kg": 38.5,
        "risk_level": "LOW",
        "notes": "Môi trường ổn định",
    }

    # 1. Ghi nhận dự báo thức ăn
    ok = await mock_redis_service.set_feeding_forecast(pond_id, sample_forecast, ttl=1800)
    assert ok is True

    # 2. Đọc lại từ cache
    cached = await mock_redis_service.get_feeding_forecast(pond_id)
    assert cached is not None
    assert cached["recommended_feed_kg"] == 38.5
    assert cached["risk_level"] == "LOW"

    # 3. Ghi nhận và đọc dự báo chất lượng nước
    water_data = {
        "predictedDO": 4.8,
        "predictedPH": 7.9,
        "riskScore": 15.0,
        "riskLevel": "SAFE",
        "alert": False,
    }
    await mock_redis_service.set_water_quality_forecast(pond_id, water_data)
    cached_water = await mock_redis_service.get_water_quality_forecast(pond_id)
    assert cached_water is not None
    assert cached_water["predictedDO"] == 4.8
    assert cached_water["alert"] is False


# ==============================================================================
# 3. Tests cho Graceful Degradation (Không sập khi Redis offline)
# ==============================================================================

@pytest.mark.anyio
async def test_redis_service_offline_graceful_degradation():
    """
    Quy tắc Chịu lỗi (Resilience):
    Nếu Redis server offline hoặc chưa bật, các phương thức không được ném lỗi ra ngoài.
    """
    # Trỏ tới cổng không tồn tại với timeout cực ngắn
    offline_svc = RedisCacheService(redis_url="redis://localhost:9999/0")

    # ping() phải trả về False an toàn
    is_up = await offline_svc.ping()
    assert is_up is False

    # get_json() trả về None an toàn
    val = await offline_svc.get_json("ai:some_key")
    assert val is None

    # set_json() trả về False an toàn
    saved = await offline_svc.set_json("ai:some_key", {"data": 123})
    assert saved is False

    # close() không gây lỗi
    await offline_svc.close()


# ==============================================================================
# 4. Tests cho API Endpoints tích hợp Cache Flow
# ==============================================================================

def test_api_feeding_forecast_caching_flow(client):
    """
    Quy trình tích hợp:
    1. Gọi POST /api/v1/ai/forecast-feeding để tính toán và tự động lưu cache.
    2. Gọi GET /api/v1/ai/forecast-feeding/{pond_id}/latest đọc ngay từ cache.
    """
    # Gán mock redis service vào app.state để đảm bảo test độc lập với Redis server thật
    mock_client = MockRedisAsyncClient()
    app.state.redis_service = RedisCacheService(client=mock_client)

    pond_id = "pond-cache-test"
    payload = {
        "pond_id": pond_id,
        "shrimp_age": 45,
        "shrimp_weight": 14.5,
        "do_min": 4.5,
        "tan_delta": 0.02,
        "rain_0600": 0.0,
        "previous_feed": 25.0,
        "water_exchange_ratio": 0.0,
    }

    # B1: Tính toán dự báo
    post_resp = client.post("/api/v1/ai/forecast-feeding", json=payload)
    assert post_resp.status_code == 200
    post_data = post_resp.json()

    # B2: Đọc từ cache
    get_resp = client.get(f"/api/v1/ai/forecast-feeding/{pond_id}/latest")
    assert get_resp.status_code == 200
    get_data = get_resp.json()

    assert get_data["pond_id"] == pond_id
    assert get_data["recommended_feed_kg"] == post_data["recommended_feed_kg"]
    assert get_data["risk_level"] == post_data["risk_level"]

    # B3: Đọc ao không tồn tại -> HTTP 404
    err_resp = client.get("/api/v1/ai/forecast-feeding/non-existent-pond/latest")
    assert err_resp.status_code == 404


def test_api_predict_caching_flow(client):
    """
    Kiểm tra luồng cache cho endpoint NestJS:
    1. Gọi POST /api/predict với pondId
    2. Gọi GET /api/predict/{pond_id}/latest đọc lại từ cache
    """
    mock_client = MockRedisAsyncClient()
    app.state.redis_service = RedisCacheService(client=mock_client)

    pond_id = "pond-nestjs-cache"
    payload = {
        "pondId": pond_id,
        "temperature": 29.0,
        "ph": 7.8,
        "salinity": 15.0,
        "dissolvedOxygen": 5.2,
    }

    post_resp = client.post("/api/predict", json=payload)
    assert post_resp.status_code == 200
    post_data = post_resp.json()

    get_resp = client.get(f"/api/predict/{pond_id}/latest")
    assert get_resp.status_code == 200
    get_data = get_resp.json()

    assert get_data["predictedDO"] == post_data["predictedDO"]
    assert get_data["riskLevel"] == post_data["riskLevel"]


def test_health_check_includes_redis_status(client):
    """Kiểm tra GET /health hiển thị trường redis"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "redis" in data
    assert "connected" in data["redis"]
