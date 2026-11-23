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
import math
import re
from typing import Any, Dict, List, Literal, Optional
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


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


# ==============================================================================
# P2-1: Schemas dự báo quỹ đạo chất lượng nước (12-24h) & rủi ro dịch bệnh
# ==============================================================================

CANONICAL_UUID_REGEX = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_CANONICAL_UUID_RE = re.compile(
    r"\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z"
)


def _validate_canonical_uuid(value: str) -> str:
    if not _CANONICAL_UUID_RE.fullmatch(value):
        raise ValueError("pondId phải đúng định dạng UUID chuẩn (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx).")
    return value


def _validate_finite_float(value: Any) -> Any:
    if isinstance(value, bool):
        raise ValueError("Giá trị số thực không được là kiểu boolean.")
    if isinstance(value, (int, float)) and not math.isfinite(float(value)):
        raise ValueError("Giá trị số thực phải hữu hạn (không chấp nhận NaN hoặc Infinity).")
    return value


def _reject_bool_int(value: Any) -> Any:
    if isinstance(value, bool):
        raise ValueError("Giá trị số nguyên không được là kiểu boolean.")
    return value


def _validate_tz_aware_iso_timestamp(value: Any) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp phải là chuỗi ISO-8601 có thông tin múi giờ.")
    raw = value.strip()
    normalized = f"{raw[:-1]}+00:00" if raw.endswith(("Z", "z")) else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("timestamp phải đúng định dạng ISO-8601 có múi giờ.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp bắt buộc phải có múi giờ (không chấp nhận naive timestamp).")
    return raw


class WaterQualityCurrentMetrics(BaseModel):
    """Chỉ số chất lượng nước hiện tại đầu vào cho dự báo quỹ đạo 12-24h"""
    model_config = ConfigDict(populate_by_name=True, allow_inf_nan=False)

    currentDO: float = Field(..., alias="current_do", ge=0.0, le=25.0, description="DO hiện tại (mg/L)")
    currentPH: float = Field(..., alias="current_ph", ge=4.0, le=11.0, description="pH hiện tại")
    currentTemp: float = Field(..., alias="current_temp", ge=10.0, le=45.0, description="Nhiệt độ hiện tại (°C)")
    salinity: float = Field(default=15.0, ge=0.0, le=50.0, description="Độ mặn (ppt)")
    turbidity: float = Field(default=25.0, ge=0.0, le=500.0, description="Độ đục (NTU)")

    @field_validator("currentDO", "currentPH", "currentTemp", "salinity", "turbidity", mode="before")
    @classmethod
    def check_finite_floats(cls, value: Any) -> Any:
        return _validate_finite_float(value)


class TelemetryHistoryPoint(BaseModel):
    """Một điểm dữ liệu telemetry lịch sử phục vụ ước lượng xu hướng biến thiên"""
    model_config = ConfigDict(populate_by_name=True, allow_inf_nan=False)

    recordedAt: str = Field(
        ...,
        validation_alias=AliasChoices("recordedAt", "recorded_at", "timestamp"),
        description="Thời điểm ghi nhận ISO-8601",
    )
    dissolvedOxygen: Optional[float] = Field(
        default=None, alias="dissolved_oxygen", ge=0.0, le=25.0, description="DO (mg/L)"
    )
    ph: Optional[float] = Field(default=None, ge=4.0, le=11.0, description="pH")
    temperature: Optional[float] = Field(default=None, ge=10.0, le=45.0, description="Nhiệt độ (°C)")
    salinity: Optional[float] = Field(default=None, ge=0.0, le=50.0, description="Độ mặn (ppt)")
    turbidity: Optional[float] = Field(default=None, ge=0.0, le=500.0, description="Độ đục (NTU)")

    @field_validator("dissolvedOxygen", "ph", "temperature", "salinity", "turbidity", mode="before")
    @classmethod
    def check_finite_floats(cls, value: Any) -> Any:
        return _validate_finite_float(value)


class PondProfileInput(BaseModel):
    """Thông tin hình học & mật độ nuôi của ao phục vụ dự báo quỹ đạo nước"""
    model_config = ConfigDict(populate_by_name=True, allow_inf_nan=False)

    areaM2: Optional[float] = Field(default=None, alias="area_m2", gt=0.0, description="Diện tích mặt ao (m²)")
    depthM: Optional[float] = Field(default=None, alias="depth_m", gt=0.0, description="Độ sâu mực nước (m)")
    shrimpDensity: Optional[float] = Field(
        default=None, alias="shrimp_density", ge=0.0, description="Mật độ thả nuôi (con/m²)"
    )

    @field_validator("areaM2", "depthM", "shrimpDensity", mode="before")
    @classmethod
    def check_finite_floats(cls, value: Any) -> Any:
        return _validate_finite_float(value)


class WaterQualityForecastRequest(BaseModel):
    """Yêu cầu dự báo quỹ đạo chất lượng nước 12-24h từ NestJS PredictionsService"""
    model_config = ConfigDict(populate_by_name=True, allow_inf_nan=False)

    pondId: str = Field(
        ...,
        alias="pond_id",
        pattern=CANONICAL_UUID_REGEX,
        description="Mã UUID chuẩn của ao nuôi",
    )
    horizonHours: int = Field(
        default=24,
        alias="horizon_hours",
        ge=12,
        le=24,
        description="Khung thời gian dự báo (12 - 24 giờ)",
    )
    stepHours: Literal[1, 2, 3, 4, 6] = Field(
        default=1,
        alias="step_hours",
        description="Bước nhảy thời gian dự báo (1, 2, 3, 4 hoặc 6 giờ)",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Mốc thời gian hiện tại ISO-8601 có múi giờ (mặc định UTC hiện tại)",
    )
    currentMetrics: WaterQualityCurrentMetrics = Field(..., alias="current_metrics")
    recentHistory: List[TelemetryHistoryPoint] = Field(default_factory=list, alias="recent_history")
    pondProfile: Optional[PondProfileInput] = Field(default=None, alias="pond_profile")

    @field_validator("pondId")
    @classmethod
    def validate_pond_id(cls, value: str) -> str:
        return _validate_canonical_uuid(value)

    @field_validator("horizonHours", "stepHours", mode="before")
    @classmethod
    def reject_bool_steps(cls, value: Any) -> Any:
        return _reject_bool_int(value)

    @field_validator("timestamp", mode="before")
    @classmethod
    def validate_timestamp(cls, value: Any) -> str:
        return _validate_tz_aware_iso_timestamp(value)


class WaterQualityForecastPoint(BaseModel):
    """Một điểm dự báo chất lượng nước trong chuỗi quỹ đạo"""
    model_config = ConfigDict(populate_by_name=True)

    offsetHours: int = Field(..., ge=1, description="Số giờ kể từ thời điểm hiện tại")
    predictedTime: str = Field(..., description="Thời điểm dự báo ISO-8601")
    predictedDO: float = Field(..., ge=0.5, le=18.0, description="DO dự báo (mg/L)")
    predictedPH: float = Field(..., ge=5.5, le=10.0, description="pH dự báo")
    predictedTemperature: float = Field(..., ge=15.0, le=42.0, description="Nhiệt độ dự báo (°C)")
    riskScore: float = Field(..., ge=0.0, le=100.0, description="Điểm rủi ro tại bước này (0-100)")
    riskLevel: NestJSRiskLevel = Field(..., description="Cấp độ rủi ro (SAFE, WARNING, DANGER)")


class WaterQualityForecastResponse(BaseModel):
    """Phản hồi dự báo quỹ đạo chất lượng nước 12-24h chuẩn hóa NestJS"""
    model_config = ConfigDict(populate_by_name=True)

    pondId: str
    horizonHours: int
    stepHours: int
    overallRiskScore: float = Field(..., ge=0.0, le=100.0)
    overallRiskLevel: NestJSRiskLevel
    series: List[WaterQualityForecastPoint]
    factors: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    latencyMs: float
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DiseaseRiskCurrentMetrics(BaseModel):
    """Chỉ số môi trường hiện tại đầu vào cho đánh giá rủi ro dịch bệnh tôm"""
    model_config = ConfigDict(populate_by_name=True, allow_inf_nan=False)

    currentDO: float = Field(..., alias="current_do", ge=0.0, le=25.0, description="DO hiện tại (mg/L)")
    currentPH: float = Field(..., alias="current_ph", ge=4.0, le=11.0, description="pH hiện tại")
    currentTemp: float = Field(..., alias="current_temp", ge=10.0, le=45.0, description="Nhiệt độ hiện tại (°C)")
    salinity: float = Field(default=15.0, ge=0.0, le=50.0, description="Độ mặn (ppt)")
    turbidity: float = Field(default=25.0, ge=0.0, le=500.0, description="Độ đục (NTU)")
    nh3: Optional[float] = Field(default=None, ge=0.0, le=20.0, description="Khí độc NH3 tự do (mg/L)")
    no2: Optional[float] = Field(default=None, ge=0.0, le=50.0, description="Nitrite NO2-N (mg/L)")

    @field_validator("currentDO", "currentPH", "currentTemp", "salinity", "turbidity", "nh3", "no2", mode="before")
    @classmethod
    def check_finite_floats(cls, value: Any) -> Any:
        return _validate_finite_float(value)


class Variability24hInput(BaseModel):
    """Biến động các thông số môi trường trong 24 giờ qua"""
    model_config = ConfigDict(populate_by_name=True, allow_inf_nan=False)

    temperatureDelta: Optional[float] = Field(
        default=None, alias="temperature_delta", ge=0.0, description="Biên độ dao động nhiệt 24h (°C)"
    )
    phDelta: Optional[float] = Field(
        default=None, alias="ph_delta", ge=0.0, description="Biên độ dao động pH 24h"
    )
    minDO: Optional[float] = Field(
        default=None, alias="min_do", ge=0.0, description="DO tối thiểu 24h (mg/L)"
    )
    minTemp: Optional[float] = Field(default=None, alias="min_temp", description="Nhiệt độ thấp nhất 24h (°C)")
    maxTemp: Optional[float] = Field(default=None, alias="max_temp", description="Nhiệt độ cao nhất 24h (°C)")

    @field_validator("temperatureDelta", "phDelta", "minDO", "minTemp", "maxTemp", mode="before")
    @classmethod
    def check_finite_floats(cls, value: Any) -> Any:
        return _validate_finite_float(value)


class DiseasePondProfileInput(BaseModel):
    """Thông tin mật độ và ngày nuôi phục vụ đánh giá nguy cơ bệnh"""
    model_config = ConfigDict(populate_by_name=True, allow_inf_nan=False)

    shrimpDensity: Optional[float] = Field(
        default=None, alias="shrimp_density", ge=0.0, description="Mật độ thả nuôi (con/m²)"
    )
    daysOfCulture: Optional[int] = Field(
        default=None, alias="days_of_culture", ge=0, description="Số ngày nuôi (DOC)"
    )

    @field_validator("shrimpDensity", mode="before")
    @classmethod
    def check_finite_density(cls, value: Any) -> Any:
        return _validate_finite_float(value)

    @field_validator("daysOfCulture", mode="before")
    @classmethod
    def check_doc_not_bool(cls, value: Any) -> Any:
        return _reject_bool_int(value)


class DiseaseRiskRequest(BaseModel):
    """Yêu cầu đánh giá nguy cơ dịch bệnh WSSV & AHPND/EMS từ NestJS PredictionsService"""
    model_config = ConfigDict(populate_by_name=True, allow_inf_nan=False)

    pondId: str = Field(
        ...,
        alias="pond_id",
        pattern=CANONICAL_UUID_REGEX,
        description="Mã UUID chuẩn của ao nuôi",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Mốc thời gian hiện tại ISO-8601 có múi giờ (mặc định UTC hiện tại)",
    )
    currentMetrics: DiseaseRiskCurrentMetrics = Field(..., alias="current_metrics")
    variability24h: Optional[Variability24hInput] = Field(default=None, alias="variability_24h")
    pondProfile: Optional[DiseasePondProfileInput] = Field(default=None, alias="pond_profile")

    @field_validator("pondId")
    @classmethod
    def validate_pond_id(cls, value: str) -> str:
        return _validate_canonical_uuid(value)

    @field_validator("timestamp", mode="before")
    @classmethod
    def validate_timestamp(cls, value: Any) -> str:
        return _validate_tz_aware_iso_timestamp(value)


class DiseaseRiskItem(BaseModel):
    """Kết quả đánh giá rủi ro cho từng bệnh cụ thể"""
    model_config = ConfigDict(populate_by_name=True)

    code: Literal["WSSV", "AHPND_EMS"]
    name: str
    riskScore: float = Field(..., ge=0.0, le=100.0)
    riskLevel: NestJSRiskLevel
    indicators: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)


class DiseaseRiskResponse(BaseModel):
    """Phản hồi đánh giá tổng hợp rủi ro dịch bệnh ao tôm chuẩn hóa NestJS"""
    model_config = ConfigDict(populate_by_name=True)

    pondId: str
    overallRiskScore: float = Field(..., ge=0.0, le=100.0)
    overallRiskLevel: NestJSRiskLevel
    diseases: List[DiseaseRiskItem]
    recommendations: List[str] = Field(default_factory=list)
    latencyMs: float
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
