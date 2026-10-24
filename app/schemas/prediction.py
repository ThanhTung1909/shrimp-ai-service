"""
Pydantic Schemas tương thích 100% với Core Backend NestJS PredictionsService
và hỗ trợ Động cơ Đánh giá Chất Lượng Nước Đa Thông Số Nuôi Tôm (Multi-Parameter Water Quality Engine).
Căn cứ khoa học:
- Đỗ Doãn Dung et al. (2025)
- Nguyễn Hữu Nghĩa et al. (2022)
- Ngô Thụy Diễm Trang et al. (2022)
- QCVN 02-19:2014/BNNPTNT
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
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
    Hỗ trợ tiếp nhận các chỉ tiêu mở rộng (TAN, NO2, ORP, độ kiềm, biến thiên mưa).
    """
    model_config = ConfigDict(populate_by_name=True)

    pond_id: Optional[str] = Field(default=None, alias="pondId", description="Mã định danh ao nuôi")
    temperature: float = Field(..., ge=0.0, le=50.0, description="Nhiệt độ nước (°C)")
    ph: float = Field(..., ge=0.0, le=14.0, description="Độ pH của nước ao")
    salinity: float = Field(default=15.0, ge=0.0, le=50.0, description="Độ mặn (ppt)")
    dissolved_oxygen: Optional[float] = Field(
        default=None,
        alias="dissolvedOxygen",
        ge=0.0,
        le=30.0,
        description="Nồng độ Oxy hòa tan hiện tại (mg/L)",
    )
    # Hỗ trợ trường do ngắn gọn nếu gửi từ cảm biến
    do: Optional[float] = Field(default=None, ge=0.0, le=30.0)
    turbidity: float = Field(default=25.0, ge=0.0, le=500.0, description="Độ đục (NTU)")
    
    # Các chỉ tiêu hóa lý sinh bổ sung theo nghiên cứu công bố (tùy chọn)
    tan: Optional[float] = Field(default=None, ge=0.0, le=20.0, description="Tổng Amoniac TAN (mg/L)")
    no2: Optional[float] = Field(default=None, alias="no2N", ge=0.0, le=50.0, description="Nitrite NO2-N (mg/L)")
    orp: Optional[float] = Field(default=None, ge=-500.0, le=1000.0, description="Thế oxy hóa khử ORP (mV)")
    alkalinity: Optional[float] = Field(default=None, ge=0.0, le=500.0, description="Độ kiềm (mg CaCO3/L)")
    delta_temp_rain: Optional[float] = Field(default=None, alias="deltaTempRain", description="Độ sụt nhiệt độ do mưa (°C)")
    delta_ph: Optional[float] = Field(default=None, alias="deltaPH", description="Biến thiên pH ngày/đêm")
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
    Phản hồi tương thích 100% với NestJS PredictionsService kèm các trường mở rộng đa thông số:
    {
      "predictedDO": 4.85,
      "predictedPH": 7.82,
      "riskScore": 15.0,
      "riskLevel": "SAFE",
      "alert": false,
      "factors": [...],
      "wqi": 88.5,
      "wqiClassification": "EXCELLENT",
      "toxicAmmoniaNH3": 0.008,
      "actionRecommendations": [...],
      "timestamp": "..."
    }
    """
    predictedDO: float = Field(..., description="Dự báo nồng độ Oxy hòa tan (mg/L)")
    predictedPH: float = Field(..., description="Dự báo độ pH nước ao")
    riskScore: float = Field(..., ge=0.0, le=100.0, description="Điểm rủi ro tổng hợp (0 - 100)")
    riskLevel: NestJSRiskLevel = Field(..., description="Cấp độ rủi ro (SAFE, WARNING, DANGER)")
    alert: bool = Field(..., description="Cờ cảnh báo kích hoạt thông báo khẩn cấp")
    factors: List[str] = Field(default_factory=list, description="Danh sách các nhân tố rủi ro chính")
    
    # Các trường mở rộng đa thông số
    wqi: Optional[float] = Field(default=None, description="Chỉ số chất lượng nước tổng hợp WQI (0-100)")
    wqiClassification: Optional[str] = Field(default=None, description="Phân hạng WQI: EXCELLENT, GOOD, ACCEPTABLE, WARNING, DANGER")
    toxicAmmoniaNH3: Optional[float] = Field(default=None, description="Nồng độ Amoniac độc tính tự do NH3-N (mg/L) theo Albert (1973)")
    parametersRisk: Optional[Dict[str, Any]] = Field(default=None, description="Đánh giá chi tiết từng chỉ số lý hóa sinh")
    actionRecommendations: Optional[List[str]] = Field(default=None, description="Khuyến nghị kỹ thuật xử lý ao nuôi")
    latencyMs: Optional[float] = Field(default=None, description="Thời gian suy luận API (ms)")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Thời điểm xuất kết quả dự báo",
    )


class ComprehensiveWaterQualityRequest(BaseModel):
    """Yêu cầu đánh giá chất lượng nước chuyên sâu cho Web Portal & Mobile App"""
    model_config = ConfigDict(populate_by_name=True)

    pond_id: str = Field(..., alias="pondId", description="Mã định danh ao nuôi")
    temperature: float = Field(..., ge=10.0, le=45.0, description="Nhiệt độ nước (°C)")
    ph: float = Field(..., ge=4.0, le=11.0, description="Độ pH")
    salinity: float = Field(default=15.0, ge=0.0, le=45.0, description="Độ mặn (ppt)")
    dissolved_oxygen: float = Field(..., alias="dissolvedOxygen", ge=0.0, le=30.0, description="DO (mg/L)")
    turbidity: float = Field(default=25.0, ge=0.0, le=500.0, description="Độ đục (NTU)")
    tan: Optional[float] = Field(default=None, ge=0.0, le=20.0, description="Tổng Amoniac TAN (mg/L)")
    no2: Optional[float] = Field(default=None, alias="no2N", ge=0.0, le=50.0, description="Nitrite NO2-N (mg/L)")
    orp: Optional[float] = Field(default=None, ge=-500.0, le=1000.0, description="Thế oxy hóa khử ORP (mV)")
    alkalinity: Optional[float] = Field(default=None, ge=0.0, le=500.0, description="Độ kiềm (mg CaCO3/L)")
    delta_temp_rain: Optional[float] = Field(default=None, alias="deltaTempRain", description="Độ sụt nhiệt độ do mưa (°C)")
    delta_ph: Optional[float] = Field(default=None, alias="deltaPH", description="Biến thiên pH ngày/đêm")


class ComprehensiveWaterQualityResponse(BaseModel):
    """Báo cáo đánh giá chất lượng nước toàn diện kèm các căn cứ khoa học công bố"""
    pond_id: str
    wqi_score: float = Field(..., ge=0.0, le=100.0, description="Điểm WQI tôm (0-100)")
    wqi_classification: str = Field(..., description="EXCELLENT, GOOD, ACCEPTABLE, WARNING, DANGER")
    risk_level: str
    alert: bool
    predicted_do_2h: float = Field(..., description="Dự báo DO sau 2 giờ (mg/L)")
    predicted_ph_2h: float = Field(..., description="Dự báo pH sau 2 giờ")
    toxic_nh3_mg_l: Optional[float] = Field(default=None, description="Khí độc NH3-N (mg/L)")
    parameters_evaluation: Dict[str, Any]
    action_recommendations: List[str]
    scientific_citations: List[str]
    latency_ms: float
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
