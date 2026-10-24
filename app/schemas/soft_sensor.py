"""
Pydantic Schemas cho AI Soft Sensor bão hòa DO (Benson & Krause 1984) và phân tích suy giảm Oxy ban đêm.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class DOSaturationRequest(BaseModel):
    """Yêu cầu tính toán độ bão hòa Oxy theo Benson & Krause (1984)"""
    temperature_c: float = Field(
        ...,
        ge=0.0,
        le=45.0,
        description="Nhiệt độ nước ao (°C, hợp lệ từ 0 đến 45°C)",
        examples=[28.5],
    )
    salinity_ppt: float = Field(
        ...,
        ge=0.0,
        le=50.0,
        description="Độ mặn nước ao (ppt hoặc ‰, hợp lệ từ 0 đến 50 ppt)",
        examples=[15.0],
    )
    pressure_atm: float = Field(
        default=1.0,
        ge=0.5,
        le=1.5,
        description="Áp suất khí quyển (atm, mặc định 1.0 atm)",
        examples=[1.0],
    )
    measured_do_mg_l: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=25.0,
        description="Nồng độ Oxy hòa tan thực tế đo được từ cảm biến (mg/L, tùy chọn)",
        examples=[6.2],
    )


class DOSaturationResponse(BaseModel):
    """Kết quả tính toán độ bão hòa và thiếu hụt oxy từ AI Soft Sensor"""
    temperature_c: float = Field(..., description="Nhiệt độ nước đầu vào (°C)")
    salinity_ppt: float = Field(..., description="Độ mặn đầu vào (ppt)")
    pressure_atm: float = Field(..., description="Áp suất khí quyển (atm)")
    do_saturation_mg_l: float = Field(
        ...,
        description="Nồng độ Oxy bão hòa lý thuyết DOsat (mg/L, Benson & Krause 1984)",
        examples=[7.12],
    )
    measured_do_mg_l: Optional[float] = Field(
        default=None,
        description="Nồng độ Oxy hòa tan đo được thực tế (mg/L)",
    )
    saturation_percentage: Optional[float] = Field(
        default=None,
        description="Tỷ lệ phần trăm bão hòa oxy (%)",
        examples=[87.08],
    )
    oxygen_deficit_mg_l: Optional[float] = Field(
        default=None,
        description="Mức độ thiếu hụt oxy so với trạng thái bão hòa (mg/L)",
        examples=[0.92],
    )
    status: str = Field(
        ...,
        description="Trạng thái oxy sinh học (HYPOXIA | LOW | OPTIMAL | SUPERSATURATED)",
        examples=["OPTIMAL"],
    )
    warning: Optional[str] = Field(
        default=None,
        description="Cảnh báo sinh học nếu phát hiện nồng độ oxy nguy hiểm",
    )


class NighttimeDODepletionRequest(BaseModel):
    """Yêu cầu mô phỏng và dự báo quỹ đạo tụt oxy ban đêm (18h chiều đến 06h sáng)"""
    initial_do: float = Field(
        ...,
        ge=0.0,
        le=15.0,
        description="Nồng độ Oxy lúc bắt đầu hoàng hôn (18:00, mg/L)",
        examples=[6.5],
    )
    start_hour: int = Field(
        default=18,
        ge=16,
        le=20,
        description="Giờ bắt đầu phân tích đêm (thường là 18:00)",
    )
    end_hour: int = Field(
        default=6,
        ge=4,
        le=8,
        description="Giờ kết thúc phân tích (thường là 06:00 sáng hôm sau)",
    )
    shrimp_biomass_kg: float = Field(
        ...,
        gt=0.0,
        le=50000.0,
        description="Tổng sinh khối tôm trong ao (kg)",
        examples=[2500.0],
    )
    aerator_status: bool = Field(
        default=True,
        description="Trạng thái vận hành quạt nước / sục khí trong đêm (True: bật, False: tắt)",
    )


class NighttimeDODepletionResponse(BaseModel):
    """Kết quả dự báo quỹ đạo tụt oxy ban đêm và cảnh báo ngạt thở"""
    initial_do: float
    min_night_do: float = Field(..., description="Nồng độ Oxy chạm đáy thấp nhất trong đêm (mg/L)")
    min_hour: int = Field(..., description="Thời điểm Oxy chạm đáy (giờ sáng, ví dụ: 4 hoặc 5)")
    hypoxia_risk: bool = Field(..., description="Cờ cảnh báo nguy cơ thiếu oxy (< 3.5 mg/L)")
    hourly_trajectory: List[Dict[str, float]] = Field(
        ...,
        description="Quỹ đạo oxy từng giờ trong suốt đêm [{\"hour\": 18, \"do\": 6.5}, ...]",
    )
    suggestion: str = Field(..., description="Khuyến nghị kỹ thuật vận hành quạt nước đêm")
