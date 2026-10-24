"""
REST API Endpoints: AI Soft Sensor bão hòa DO và phân tích suy giảm oxy ban đêm.
POST /api/v1/ai/soft-sensor/do-saturation
POST /api/v1/ai/soft-sensor/nighttime-depletion
Do Backend-Integration-Agent chủ trì.
"""

import logging
from fastapi import APIRouter, status

from app.models.soft_sensor import (
    analyze_do_saturation_status,
    benson_krause_do_saturation,
    predict_nighttime_do_depletion,
)
from app.schemas.soft_sensor import (
    DOSaturationRequest,
    DOSaturationResponse,
    NighttimeDODepletionRequest,
    NighttimeDODepletionResponse,
)

logger = logging.getLogger("ai_service.api.soft_sensor")

router = APIRouter(prefix="/ai/soft-sensor", tags=["AI Soft Sensor (Benson & Krause 1984)"])


@router.post(
    "/do-saturation",
    response_model=DOSaturationResponse,
    status_code=status.HTTP_200_OK,
    summary="Ước lượng độ bão hòa Oxy hòa tan (Benson & Krause 1984)",
    description="Tính toán nồng độ Oxy hòa tan bão hòa DOsat lý thuyết và phân tích mức độ thiếu hụt oxy.",
)
async def estimate_do_saturation(request: DOSaturationRequest) -> DOSaturationResponse:
    """
    AI Soft Sensor áp dụng phương trình nhiệt động học Benson & Krause (1984) chuẩn USGS.
    """
    do_sat = benson_krause_do_saturation(
        request.temperature_c,
        request.salinity_ppt,
        request.pressure_atm,
    )

    measured = request.measured_do_mg_l if request.measured_do_mg_l is not None else do_sat
    analysis = analyze_do_saturation_status(
        request.temperature_c,
        request.salinity_ppt,
        measured,
    )

    return DOSaturationResponse(
        temperature_c=request.temperature_c,
        salinity_ppt=request.salinity_ppt,
        pressure_atm=request.pressure_atm,
        do_saturation_mg_l=do_sat,
        measured_do_mg_l=request.measured_do_mg_l,
        saturation_percentage=analysis["saturation_percentage"],
        oxygen_deficit_mg_l=analysis["oxygen_deficit"],
        status=analysis["status"],
        warning=analysis.get("action_suggestion"),
    )


@router.post(
    "/nighttime-depletion",
    response_model=NighttimeDODepletionResponse,
    status_code=status.HTTP_200_OK,
    summary="Dự báo quỹ đạo suy giảm Oxy ban đêm (18h - 06h)",
    description="Mô phỏng động lực học tiêu thụ oxy sinh học của đàn tôm trong đêm và cảnh báo nguy cơ ngạt.",
)
async def predict_nighttime_depletion(request: NighttimeDODepletionRequest) -> NighttimeDODepletionResponse:
    """
    Phân tích quỹ đạo tụt oxy ban đêm và đưa ra khuyến nghị vận hành quạt nước.
    """
    # Tính số giờ ban đêm từ start_hour (18) đến end_hour (6) -> 12 giờ
    hours_ahead = (request.end_hour - request.start_hour) % 24
    if hours_ahead == 0:
        hours_ahead = 12

    # Hệ số sinh khối chuẩn hóa (ao 2500kg sinh khối = 1.0)
    density_factor = max(0.5, min(3.0, request.shrimp_biomass_kg / 2500.0))

    result = predict_nighttime_do_depletion(
        current_temp=28.5,
        salinity=15.0,
        current_do=request.initial_do,
        hours_ahead=hours_ahead,
        aeration_active=request.aerator_status,
        shrimp_density_factor=density_factor,
    )

    # Chuyển đổi trajectory sang format [{"hour": ..., "do": ...}]
    raw_traj = result.get("trajectory", [])
    hourly_trajectory = []
    for item in raw_traj:
        step = item.get("hour_step", item.get("hour", 0))
        clock_hour = (request.start_hour + step) % 24
        hourly_trajectory.append({"hour": clock_hour, "do": item["projected_do"]})

    min_do = float(result.get("minimum_projected_do", request.initial_do))
    min_hour = (request.start_hour + int(result.get("lowest_hour", hours_ahead))) % 24
    hypoxia = min_do < 3.5

    return NighttimeDODepletionResponse(
        initial_do=request.initial_do,
        min_night_do=min_do,
        min_hour=min_hour,
        hypoxia_risk=hypoxia,
        hourly_trajectory=hourly_trajectory,
        suggestion=str(result.get("alert_message", "Duy trì quạt nước ban đêm.")),
    )

