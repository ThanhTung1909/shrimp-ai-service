"""
Pydantic Schemas cho API dự báo lượng thức ăn tôm và đánh giá rủi ro bỏ ăn.
Tuân thủ tuyệt đối Feature Integrity Rule: Không lược bỏ bất kỳ biến nào trong 7 biến thực nghiệm bắt buộc.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class FeedingRiskLevel(str, Enum):
    """Mức độ rủi ro dinh dưỡng / môi trường đối với cữ ăn"""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FeedingForecastRequest(BaseModel):
    """
    Dữ liệu yêu cầu dự báo thức ăn cho ao tôm.
    Bắt buộc đủ 7 biến thực nghiệm theo Feature Integrity Rule.
    """
    pond_id: str = Field(default="pond-default", description="Mã định danh ao nuôi")

    # 7 BIẾN THỰC NGHIỆM BẮT BUỘC:
    shrimp_age: int = Field(
        ...,
        ge=1,
        le=180,
        description="Tuổi tôm tính theo ngày nuôi (1 - 180 ngày)",
        examples=[45],
    )
    shrimp_weight: float = Field(
        ...,
        gt=0.0,
        le=100.0,
        description="Khối lượng tôm trung bình (g/con)",
        examples=[14.5],
    )
    do_min: float = Field(
        ...,
        ge=0.0,
        le=15.0,
        description="Nồng độ Oxy hòa tan tối thiểu trong 12h/24h qua (mg/L)",
        examples=[4.2],
    )
    tan_delta: float = Field(
        ...,
        ge=-10.0,
        le=10.0,
        description="Độ biến thiên tổng amoniac TAN giữa 2 chu kỳ đo gần nhất (mg/L)",
        examples=[0.05],
    )
    rain_0600: float = Field(
        ...,
        ge=0.0,
        le=500.0,
        description="Lượng mưa lúc 06:00 sáng (mm) - phản ánh nguy cơ sốc nước và bỏ ăn",
        examples=[0.0],
    )
    previous_feed: float = Field(
        ...,
        gt=0.0,
        le=1000.0,
        description="Lượng thức ăn cữ trước đã tiêu thụ (kg)",
        examples=[25.0],
    )
    water_exchange_ratio: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Tỷ lệ thay nước trong ngày (%)",
        examples=[0.0],
    )

    # Thông tin bổ sung
    feed_time: Optional[str] = Field(
        default=None,
        description="Thời gian cữ ăn (ví dụ: '07:00', '11:00', '15:00', '19:00')",
        examples=["07:00"],
    )
    notes: Optional[str] = Field(default=None, description="Ghi chú thêm về đàn tôm")

    def to_feature_list(self) -> List[float]:
        """Chuyển đổi thành danh sách 7 giá trị theo đúng thứ tự REQUIRED_FEEDING_FEATURES"""
        return [
            float(self.shrimp_age),
            float(self.shrimp_weight),
            float(self.do_min),
            float(self.tan_delta),
            float(self.rain_0600),
            float(self.previous_feed),
            float(self.water_exchange_ratio),
        ]


class FeedingForecastResponse(BaseModel):
    """Kết quả dự báo lượng thức ăn khuyến nghị và cảnh báo rủi ro"""
    pond_id: str = Field(..., description="Mã ao nuôi")
    recommended_feed_kg: float = Field(
        ...,
        description="Lượng thức ăn khuyến nghị cho cữ ăn tới (kg, làm tròn 2 chữ số)",
        examples=[38.88],
    )
    risk_level: FeedingRiskLevel = Field(
        ...,
        description="Mức độ rủi ro đối với sức ăn của tôm",
        examples=[FeedingRiskLevel.LOW],
    )
    confidence_score: float = Field(
        default=0.95,
        ge=0.0,
        le=1.0,
        description="Độ tin cậy của mô hình AI đối với dự báo",
    )
    factors_impact: Dict[str, str] = Field(
        default_factory=dict,
        description="Đánh giá chi tiết ảnh hưởng của từng yếu tố môi trường",
    )
    recommendation_note: str = Field(
        ...,
        description="Khuyến nghị kỹ thuật chi tiết cho người nuôi",
    )
    model_version: str = Field(default="1.0.0", description="Phiên bản mô hình AI")
    latency_ms: float = Field(..., description="Thời gian suy luận của AI Service (ms)")
    computed_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Thời điểm tính toán kết quả",
    )
