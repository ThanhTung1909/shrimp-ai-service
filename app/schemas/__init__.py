"""
Gói Pydantic Schemas phục vụ kiểm tra tính hợp lệ dữ liệu của AquaSense AI Microservice.
Do Backend-Integration-Agent quản lý.
"""

from app.schemas.common import APIResponse, ErrorResponse, HealthResponse
from app.schemas.feeding import (
    FeedingForecastRequest,
    FeedingForecastResponse,
    FeedingRiskLevel,
)
from app.schemas.prediction import (
    ComprehensiveWaterQualityRequest,
    ComprehensiveWaterQualityResponse,
    DiseasePondProfileInput,
    DiseaseRiskCurrentMetrics,
    DiseaseRiskItem,
    DiseaseRiskRequest,
    DiseaseRiskResponse,
    NestJSPredictRequest,
    NestJSPredictResponse,
    NestJSRiskLevel,
    PondProfileInput,
    TelemetryHistoryPoint,
    Variability24hInput,
    WaterQualityCurrentMetrics,
    WaterQualityForecastPoint,
    WaterQualityForecastRequest,
    WaterQualityForecastResponse,
)
from app.schemas.soft_sensor import (
    DOSaturationRequest,
    DOSaturationResponse,
    NighttimeDODepletionRequest,
    NighttimeDODepletionResponse,
)

__all__ = [
    "HealthResponse",
    "APIResponse",
    "ErrorResponse",
    "FeedingForecastRequest",
    "FeedingForecastResponse",
    "FeedingRiskLevel",
    "NestJSPredictRequest",
    "NestJSPredictResponse",
    "NestJSRiskLevel",
    "ComprehensiveWaterQualityRequest",
    "ComprehensiveWaterQualityResponse",
    "WaterQualityCurrentMetrics",
    "TelemetryHistoryPoint",
    "PondProfileInput",
    "WaterQualityForecastRequest",
    "WaterQualityForecastPoint",
    "WaterQualityForecastResponse",
    "DiseaseRiskCurrentMetrics",
    "Variability24hInput",
    "DiseasePondProfileInput",
    "DiseaseRiskRequest",
    "DiseaseRiskItem",
    "DiseaseRiskResponse",
    "DOSaturationRequest",
    "DOSaturationResponse",
    "NighttimeDODepletionRequest",
    "NighttimeDODepletionResponse",
]
