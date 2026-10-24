"""
Unit tests cho TASK-BE-03: REST API Endpoints.
Kiểm tra chi tiết:
- POST /api/v1/ai/forecast-feeding (Latency < 500ms, điều chỉnh sinh học)
- POST /api/predict (Tương thích 100% Core Backend NestJS)
- POST /api/v1/ai/soft-sensor/do-saturation (Benson & Krause 1984)
- POST /api/v1/ai/soft-sensor/nighttime-depletion
Do Backend-Integration-Agent chủ trì.
"""

import time
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    """Khởi tạo TestClient nạp sẵn Lifespan models"""
    with TestClient(app) as test_client:
        yield test_client


# ==============================================================================
# 1. Tests cho POST /api/v1/ai/forecast-feeding
# ==============================================================================

def test_forecast_feeding_success_and_latency(client):
    """
    Inference Latency Rule: API suy luận phải đạt thời gian phản hồi < 500 ms.
    Với mô hình nạp sẵn trong RAM, latency thực tế < 50 ms.
    """
    payload = {
        "pond_id": "pond-A1",
        "shrimp_age": 45,
        "shrimp_weight": 14.5,
        "do_min": 4.5,
        "tan_delta": 0.02,
        "rain_0600": 0.0,
        "previous_feed": 25.0,
        "water_exchange_ratio": 0.0,
        "feed_time": "07:00",
    }

    t0 = time.perf_counter()
    response = client.post("/api/v1/ai/forecast-feeding", json=payload)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert response.status_code == 200, f"Lỗi: {response.text}"
    data = response.json()

    assert data["pond_id"] == "pond-A1"
    assert data["recommended_feed_kg"] > 0.0
    assert data["risk_level"] == "LOW"
    assert data["confidence_score"] >= 0.90
    assert data["model_version"] == "1.0.0"
    assert "latency_ms" in data

    # Kiểm tra quy tắc độ trễ
    assert elapsed_ms < 500.0, f"Vi phạm Inference Latency Rule: {elapsed_ms:.2f} ms > 500 ms"


def test_forecast_feeding_rain_shock_reduces_feed(client):
    """Kiểm tra phản ứng sinh học: Mưa lớn lúc 06:00 làm tăng rủi ro và giảm khẩu phần"""
    payload = {
        "pond_id": "pond-A2",
        "shrimp_age": 50,
        "shrimp_weight": 16.0,
        "do_min": 4.2,
        "tan_delta": 0.05,
        "rain_0600": 35.0,  # Mưa lớn 35mm
        "previous_feed": 30.0,
        "water_exchange_ratio": 0.0,
    }

    response = client.post("/api/v1/ai/forecast-feeding", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["risk_level"] == "HIGH"
    assert "rain_0600" in data["factors_impact"]
    assert "Mưa lớn" in data["factors_impact"]["rain_0600"]
    assert "Giảm" in data["recommendation_note"]


def test_forecast_feeding_hypoxia_critical_alert(client):
    """Kiểm tra cấp cứu khi DO tối thiểu tụt dưới 3.0 mg/L"""
    payload = {
        "pond_id": "pond-A3",
        "shrimp_age": 60,
        "shrimp_weight": 20.0,
        "do_min": 2.4,  # Nguy cấp
        "tan_delta": 0.1,
        "rain_0600": 0.0,
        "previous_feed": 35.0,
        "water_exchange_ratio": 0.0,
    }

    response = client.post("/api/v1/ai/forecast-feeding", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["risk_level"] == "CRITICAL"
    assert "ngạt khí" in data["factors_impact"]["do_min"]
    assert "oxy viên" in data["recommendation_note"].lower()


def test_forecast_feeding_validation_failure(client):
    """Kiểm tra chặn lỗi 422 khi thiếu 1 trong 7 biến thực nghiệm bắt buộc"""
    invalid_payload = {
        "pond_id": "pond-err",
        "shrimp_age": 45,
        "shrimp_weight": 14.5,
        "do_min": 4.2,
        # Thiếu rain_0600
        "tan_delta": 0.05,
        "previous_feed": 25.0,
        "water_exchange_ratio": 0.0,
    }

    response = client.post("/api/v1/ai/forecast-feeding", json=invalid_payload)
    assert response.status_code == 422
    data = response.json()
    assert data["status"] == "error"
    assert data["error_type"] == "VALIDATION_ERROR"


# ==============================================================================
# 2. Tests cho POST /api/predict (NestJS Compatibility)
# ==============================================================================

def test_predict_nestjs_compatibility_camel_case(client):
    """
    Kiểm tra endpoint POST /api/predict tương thích 100% với NestJS Core Backend:
    Chấp nhận payload dạng camelCase (pondId, dissolvedOxygen)
    """
    payload_camel = {
        "pondId": "pond-nestjs-1",
        "temperature": 29.5,
        "ph": 7.9,
        "salinity": 15.0,
        "dissolvedOxygen": 5.6,
        "turbidity": 12.0,
    }

    response = client.post("/api/predict", json=payload_camel)
    assert response.status_code == 200
    data = response.json()

    # Kiểm tra chính xác các trường NestJS cần
    assert "predictedDO" in data
    assert "predictedPH" in data
    assert "riskScore" in data
    assert "riskLevel" in data
    assert "alert" in data
    assert "factors" in data
    assert "timestamp" in data

    assert data["riskLevel"] == "SAFE"
    assert data["alert"] is False
    assert isinstance(data["factors"], list)


def test_predict_nestjs_danger_alert(client):
    """Kiểm tra kích hoạt cờ alert khi chất lượng nước nguy cấp"""
    payload_danger = {
        "pond_id": "pond-danger",
        "temperature": 34.0,  # Quá nóng
        "ph": 9.2,           # pH kiềm cao
        "salinity": 20.0,
        "dissolved_oxygen": 2.6,  # Tụt oxy nghiêm trọng
    }

    response = client.post("/api/predict", json=payload_danger)
    assert response.status_code == 200
    data = response.json()

    assert data["riskLevel"] == "DANGER"
    assert data["alert"] is True
    assert data["riskScore"] >= 65.0


# ==============================================================================
# 3. Tests cho AI Soft Sensor Endpoints
# ==============================================================================

def test_soft_sensor_do_saturation(client):
    """
    Kiểm tra POST /api/v1/ai/soft-sensor/do-saturation
    Đối chiếu benchmark USGS: 25°C, 0 ppt, 1 atm -> DOsat ≈ 8.263 mg/L
    """
    payload = {
        "temperature_c": 25.0,
        "salinity_ppt": 0.0,
        "pressure_atm": 1.0,
        "measured_do_mg_l": 7.2,
    }

    response = client.post("/api/v1/ai/soft-sensor/do-saturation", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert abs(data["do_saturation_mg_l"] - 8.263) < 0.05
    assert data["saturation_percentage"] is not None
    assert data["status"] == "OPTIMAL"


def test_soft_sensor_nighttime_depletion(client):
    """
    Kiểm tra POST /api/v1/ai/soft-sensor/nighttime-depletion
    """
    payload = {
        "initial_do": 6.5,
        "start_hour": 18,
        "end_hour": 6,
        "shrimp_biomass_kg": 3000.0,
        "aerator_status": True,
    }

    response = client.post("/api/v1/ai/soft-sensor/nighttime-depletion", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert "min_night_do" in data
    assert "min_hour" in data
    assert "hypoxia_risk" in data
    assert "hourly_trajectory" in data
    assert len(data["hourly_trajectory"]) >= 12
    assert "suggestion" in data
