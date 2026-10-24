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
    "DOSaturationRequest",
    "DOSaturationResponse",
    "NighttimeDODepletionRequest",
    "NighttimeDODepletionResponse",
]
