"""
Pydantic Schemas chung cho phản hồi API, trạng thái và lỗi hệ thống.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Schema trạng thái sức khỏe dịch vụ GET /health"""
    status: str = Field(..., description="Trạng thái dịch vụ (ok | degraded | error)")
    service: str = Field(default="AquaSense AI Microservice")
    environment: str = Field(default="development")
    port: int = Field(default=8000)
    model_loaded: bool = Field(..., description="Mô hình ML đã nạp sẵn trong RAM")
    model_version: Optional[str] = Field(default=None)
    database: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class APIResponse(BaseModel):
    """Generic Wrapper cho phản hồi thành công"""
    status: str = Field(default="success")
    data: Any = Field(...)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ErrorDetail(BaseModel):
    """Chi tiết lỗi từng trường validation"""
    field: str
    message: str
    type: Optional[str] = None


class ErrorResponse(BaseModel):
    """Chuẩn phản hồi lỗi hệ thống"""
    status: str = Field(default="error")
    error_type: str = Field(..., description="Mã phân loại lỗi")
    message: str = Field(..., description="Mô tả lỗi dễ hiểu")
    errors: Optional[List[ErrorDetail]] = None
    detail: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
