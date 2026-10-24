"""
Unit tests cho TASK-BE-02: Pydantic Validation Schemas.
Kiểm tra Feature Integrity Rule (7 biến bắt buộc), NestJS compatibility, Benson & Krause soft sensor.
Do Backend-Integration-Agent chủ trì.
"""

import pytest
from pydantic import ValidationError

from app.schemas.common import APIResponse, ErrorResponse, HealthResponse
from app.schemas.feeding import (
    FeedingForecastRequest,
    FeedingForecastResponse,
    FeedingRiskLevel,
)
from app.schemas.prediction import (
    NestJSPredictRequest,
    NestJSPredictResponse,
    NestJSRiskLevel,
)
from app.schemas.soft_sensor import (
    DOSaturationRequest,
    DOSaturationResponse,
    NighttimeDODepletionRequest,
    NighttimeDODepletionResponse,
)


# ==============================================================================
# 1. Tests cho Feeding Forecast Schemas (Feature Integrity Rule)
# ==============================================================================

def test_feeding_forecast_request_valid():
    """Kiểm tra khởi tạo hợp lệ với đầy đủ 7 biến thực nghiệm bắt buộc"""
    payload = {
        "pond_id": "pond-A1",
        "shrimp_age": 45,
        "shrimp_weight": 14.5,
        "do_min": 4.2,
        "tan_delta": 0.05,
        "rain_0600": 15.0,
        "previous_feed": 28.5,
        "water_exchange_ratio": 10.0,
        "feed_time": "07:00",
        "notes": "Tôm ăn khỏe sau cơn mưa sáng",
    }
    req = FeedingForecastRequest(**payload)
    assert req.shrimp_age == 45
    assert req.shrimp_weight == 14.5
    assert req.do_min == 4.2
    assert req.tan_delta == 0.05
    assert req.rain_0600 == 15.0
    assert req.previous_feed == 28.5
    assert req.water_exchange_ratio == 10.0

    # Kiểm tra phương thức to_feature_list xuất đúng 7 phần tử
    feat_list = req.to_feature_list()
    assert len(feat_list) == 7
    assert feat_list == [45.0, 14.5, 4.2, 0.05, 15.0, 28.5, 10.0]


def test_feeding_forecast_request_missing_required_features():
    """
    Feature Integrity Rule:
    Tuyệt đối không được thiếu bất kỳ biến nào trong 7 biến thực nghiệm bắt buộc.
    """
    valid_base = {
        "pond_id": "pond-A1",
        "shrimp_age": 45,
        "shrimp_weight": 14.5,
        "do_min": 4.2,
        "tan_delta": 0.05,
        "rain_0600": 0.0,
        "previous_feed": 25.0,
        "water_exchange_ratio": 0.0,
    }

    # Thử lần lượt xóa từng biến trong 7 biến và kiểm tra ValidationError
    required_keys = [
        "shrimp_age",
        "shrimp_weight",
        "do_min",
        "tan_delta",
        "rain_0600",
        "previous_feed",
        "water_exchange_ratio",
    ]
    for key in required_keys:
        incomplete_payload = valid_base.copy()
        del incomplete_payload[key]
        with pytest.raises(ValidationError) as exc_info:
            FeedingForecastRequest(**incomplete_payload)
        assert key in str(exc_info.value), f"Phải báo lỗi khi thiếu trường {key}"


def test_feeding_forecast_request_boundary_violations():
    """Kiểm tra validation chặn các giá trị nằm ngoài giới hạn sinh học"""
    # 1. Tuổi tôm <= 0 hoặc > 180
    with pytest.raises(ValidationError):
        FeedingForecastRequest(
            shrimp_age=0, shrimp_weight=10.0, do_min=4.0, tan_delta=0.0, rain_0600=0.0, previous_feed=20.0, water_exchange_ratio=0.0
        )
    with pytest.raises(ValidationError):
        FeedingForecastRequest(
            shrimp_age=200, shrimp_weight=10.0, do_min=4.0, tan_delta=0.0, rain_0600=0.0, previous_feed=20.0, water_exchange_ratio=0.0
        )

    # 2. Khối lượng tôm <= 0
    with pytest.raises(ValidationError):
        FeedingForecastRequest(
            shrimp_age=30, shrimp_weight=0.0, do_min=4.0, tan_delta=0.0, rain_0600=0.0, previous_feed=20.0, water_exchange_ratio=0.0
        )

    # 3. DO tối thiểu < 0
    with pytest.raises(ValidationError):
        FeedingForecastRequest(
            shrimp_age=30, shrimp_weight=5.0, do_min=-1.0, tan_delta=0.0, rain_0600=0.0, previous_feed=20.0, water_exchange_ratio=0.0
        )

    # 4. Lượng mưa âm
    with pytest.raises(ValidationError):
        FeedingForecastRequest(
            shrimp_age=30, shrimp_weight=5.0, do_min=4.0, tan_delta=0.0, rain_0600=-5.0, previous_feed=20.0, water_exchange_ratio=0.0
        )

    # 5. Tỷ lệ thay nước > 100%
    with pytest.raises(ValidationError):
        FeedingForecastRequest(
            shrimp_age=30, shrimp_weight=5.0, do_min=4.0, tan_delta=0.0, rain_0600=0.0, previous_feed=20.0, water_exchange_ratio=150.0
        )


def test_feeding_forecast_response_serialization():
    """Kiểm tra schema phản hồi dự báo thức ăn"""
    resp = FeedingForecastResponse(
        pond_id="pond-A1",
        recommended_feed_kg=35.5,
        risk_level=FeedingRiskLevel.MEDIUM,
        confidence_score=0.92,
        factors_impact={"rain_0600": "Mưa 25mm làm giảm 15% nhu cầu ăn"},
        recommendation_note="Giảm 15% lượng thức ăn cữ sáng; bật quạt tăng oxy.",
        model_version="1.0.0",
        latency_ms=4.8,
    )
    data = resp.model_dump()
    assert data["pond_id"] == "pond-A1"
    assert data["recommended_feed_kg"] == 35.5
    assert data["risk_level"] == "MEDIUM"
    assert data["latency_ms"] == 4.8
    assert "computed_at" in data


# ==============================================================================
# 2. Tests cho NestJS Prediction Schemas (Tương thích 100%)
# ==============================================================================

def test_nestjs_predict_request_camel_and_snake_case():
    """Kiểm tra NestJSPredictRequest tiếp nhận cả camelCase từ NestJS và snake_case"""
    # 1. Dạng camelCase từ NestJS Core Backend
    payload_camel = {
        "pondId": "pond-101",
        "temperature": 29.5,
        "ph": 7.8,
        "salinity": 18.0,
        "dissolvedOxygen": 5.4,
        "turbidity": 12.0,
    }
    req1 = NestJSPredictRequest(**payload_camel)
    assert req1.pond_id == "pond-101"
    assert req1.current_do == 5.4
    assert req1.temperature == 29.5

    # 2. Dạng snake_case với 'do'
    payload_snake = {
        "pond_id": "pond-102",
        "temperature": 30.0,
        "ph": 8.1,
        "do": 4.6,
    }
    req2 = NestJSPredictRequest(**payload_snake)
    assert req2.pond_id == "pond-102"
    assert req2.current_do == 4.6


def test_nestjs_predict_response_structure():
    """Kiểm tra cấu trúc NestJSPredictResponse khớp chính xác interface của NestJS"""
    resp = NestJSPredictResponse(
        predictedDO=4.65,
        predictedPH=7.95,
        riskScore=25.0,
        riskLevel=NestJSRiskLevel.SAFE,
        alert=False,
        factors=["Chất lượng nước ổn định", "DO tối ưu"],
    )
    data = resp.model_dump()
    assert data["predictedDO"] == 4.65
    assert data["predictedPH"] == 7.95
    assert data["riskScore"] == 25.0
    assert data["riskLevel"] == "SAFE"
    assert data["alert"] is False
    assert len(data["factors"]) == 2
    assert "timestamp" in data


# ==============================================================================
# 3. Tests cho AI Soft Sensor Schemas
# ==============================================================================

def test_do_saturation_request_and_response():
    """Kiểm tra schema độ bão hòa Benson & Krause"""
    req = DOSaturationRequest(
        temperature_c=28.0,
        salinity_ppt=15.0,
        pressure_atm=1.0,
        measured_do_mg_l=6.5,
    )
    assert req.temperature_c == 28.0
    assert req.salinity_ppt == 15.0

    resp = DOSaturationResponse(
        temperature_c=28.0,
        salinity_ppt=15.0,
        pressure_atm=1.0,
        do_saturation_mg_l=7.21,
        measured_do_mg_l=6.5,
        saturation_percentage=90.15,
        oxygen_deficit_mg_l=0.71,
        status="OPTIMAL",
    )
    assert resp.status == "OPTIMAL"
    assert resp.do_saturation_mg_l == 7.21


def test_do_saturation_request_invalid_ranges():
    """Kiểm tra biên nhiệt độ và độ mặn"""
    with pytest.raises(ValidationError):
        DOSaturationRequest(temperature_c=-5.0, salinity_ppt=15.0)
    with pytest.raises(ValidationError):
        DOSaturationRequest(temperature_c=55.0, salinity_ppt=15.0)
    with pytest.raises(ValidationError):
        DOSaturationRequest(temperature_c=28.0, salinity_ppt=65.0)


def test_nighttime_do_depletion_schemas():
    """Kiểm tra schema dự báo oxy đêm"""
    req = NighttimeDODepletionRequest(
        initial_do=6.5,
        start_hour=18,
        end_hour=6,
        shrimp_biomass_kg=3000.0,
        aerator_status=True,
    )
    assert req.shrimp_biomass_kg == 3000.0

    resp = NighttimeDODepletionResponse(
        initial_do=6.5,
        min_night_do=4.1,
        min_hour=5,
        hypoxia_risk=False,
        hourly_trajectory=[{"hour": 18, "do": 6.5}, {"hour": 5, "do": 4.1}],
        suggestion="Duy trì quạt nước tiêu chuẩn ban đêm.",
    )
    assert resp.min_hour == 5
    assert resp.hypoxia_risk is False


# ==============================================================================
# 4. Tests cho Common Schemas
# ==============================================================================

def test_common_schemas():
    """Kiểm tra HealthResponse, APIResponse và ErrorResponse"""
    h = HealthResponse(
        status="ok",
        model_loaded=True,
        model_version="1.0.0",
        database={"connected": True},
    )
    assert h.status == "ok"
    assert h.model_loaded is True

    api_resp = APIResponse(data={"feed_kg": 25.0})
    assert api_resp.status == "success"
    assert api_resp.data["feed_kg"] == 25.0

    err_resp = ErrorResponse(
        error_type="VALIDATION_ERROR",
        message="Thiếu trường dữ liệu",
    )
    assert err_resp.error_type == "VALIDATION_ERROR"
