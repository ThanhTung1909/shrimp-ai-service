"""
Pydantic Schemas tương thích 100% với Core Backend NestJS PredictionsService.
Cho phép tích hợp tức thì qua endpoint POST /api/predict mà không cần sửa đổi backend NestJS.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class NestJSRiskLevel(str, Enum):
    """Mức độ rủi ro theo định dạng của NestJS"""
    SAFE = "SAFE"
    WARNING = "WARNING"
    DANGER = "DANGER"


class NestJSPredictRequest(BaseModel):
    """
    Dữ liệu yêu cầu dự báo chất lượng nước từ Core Backend NestJS.
    Chấp nhận cả camelCase và snake_case để tương thích linh hoạt.
    """
    model_config = ConfigDict(populate_by_name=True)

    pond_id: Optional[str] = Field(default=None, alias="pondId")
    temperature: float = Field(..., ge=0.0, le=50.0, description="Nhiệt độ nước (°C)")
    ph: float = Field(..., ge=0.0, le=14.0, description="Độ pH của nước ao")
    salinity: float = Field(default=15.0, ge=0.0, le=50.0, description="Độ mặn (ppt)")
    dissolved_oxygen: Optional[float] = Field(
        default=None,
        alias="dissolvedOxygen",
        ge=0.0,
        le=20.0,
        description="Nồng độ Oxy hòa tan hiện tại (mg/L)",
    )
    # Hỗ trợ trường do ngắn gọn nếu gửi từ cảm biến
    do: Optional[float] = Field(default=None, ge=0.0, le=20.0)
    turbidity: float = Field(default=10.0, ge=0.0, le=500.0, description="Độ đục (NTU)")
    timestamp: Optional[str] = Field(default=None, description="Thời điểm ghi nhận telemetry")

    @property
    def current_do(self) -> float:
        """Lấy giá trị Oxy hòa tan từ trường dissolved_oxygen hoặc do"""
        if self.dissolved_oxygen is not None:
            return float(self.dissolved_oxygen)
        if self.do is not None:
            return float(self.do)
        return 5.0  # Mặc định an toàn nếu không truyền


class NestJSPredictResponse(BaseModel):
    """
    Phản hồi tương thích 100% với NestJS PredictionsService:
    {
      "predictedDO": 4.85,
      "predictedPH": 7.82,
      "riskScore": 15.0,
      "riskLevel": "SAFE",
      "alert": false,
      "factors": ["Nhiệt độ ổn định", "DO tối ưu"],
      "timestamp": "..."
    }
    """
    predictedDO: float = Field(..., description="Dự báo nồng độ Oxy hòa tan (mg/L)")
    predictedPH: float = Field(..., description="Dự báo độ pH nước ao")
    riskScore: float = Field(..., ge=0.0, le=100.0, description="Điểm rủi ro tổng hợp (0 - 100)")
    riskLevel: NestJSRiskLevel = Field(..., description="Cấp độ rủi ro (SAFE, WARNING, DANGER)")
    alert: bool = Field(..., description="Cờ cảnh báo kích hoạt thông báo khẩn cấp")
    factors: List[str] = Field(default_factory=list, description="Danh sách các nhân tố rủi ro chính")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Thời điểm xuất kết quả dự báo",
    )
