"""
REST API Endpoint: Dự báo chất lượng nước tương thích 100% với Core Backend NestJS.
POST /api/predict (và POST /api/v1/predict)
Khớp từng trường dữ liệu với NestJS PredictionsService:
{
  "predictedDO": 4.85,
  "predictedPH": 7.82,
  "riskScore": 15.0,
  "riskLevel": "SAFE",
  "alert": false,
  "factors": [...],
  "timestamp": "..."
}
Do Backend-Integration-Agent chủ trì.
"""

from datetime import datetime, timezone
import logging
from typing import List, Tuple
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_redis_cache
from app.models.soft_sensor import (
    analyze_do_saturation_status,
    benson_krause_do_saturation,
)
from app.schemas.prediction import (
    NestJSPredictRequest,
    NestJSPredictResponse,
    NestJSRiskLevel,
)
from app.services.redis_cache import RedisCacheService

logger = logging.getLogger("ai_service.api.predictions")

router = APIRouter(tags=["NestJS Predictions Compatibility"])


def compute_water_quality_forecast(
    req: NestJSPredictRequest,
) -> Tuple[float, float, float, NestJSRiskLevel, bool, List[str]]:
    """
    Mô hình tính toán dự báo chất lượng nước trong 2-4 giờ tới:
    Kết hợp phương trình nhiệt động học Benson & Krause và động lực học hồ nuôi.
    """
    current_do = req.current_do
    temp = req.temperature
    ph = req.ph
    salinity = req.salinity

    # 1. Tính toán độ bão hòa lý thuyết theo Benson & Krause (1984)
    do_sat = benson_krause_do_saturation(temp, salinity, pressure_atm=1.0)
    sat_analysis = analyze_do_saturation_status(temp, salinity, current_do)

    factors: List[str] = []
    risk_points = 0.0

    # 2. Dự báo xu hướng DO
    # Tốc độ suy giảm tự nhiên do hô hấp (mg/L/h)
    respiration_rate = 0.15 + (temp - 25.0) * 0.01 if temp > 25.0 else 0.15
    predicted_do = max(1.0, current_do - (respiration_rate * 2.0))

    if current_do < 3.5:
        risk_points += 55.0
        factors.append(f"Oxy hòa tan hiện tại rất thấp ({current_do:.2f} mg/L < 3.5 mg/L)")
    elif current_do < 4.2:
        risk_points += 25.0
        factors.append(f"Oxy hòa tan ở mức cảnh giác ({current_do:.2f} mg/L)")
    else:
        factors.append(f"Oxy hòa tan dồi dào ({current_do:.2f} mg/L - {sat_analysis['saturation_percentage']:.1f}% bão hòa)")

    if predicted_do < 3.0:
        risk_points += 30.0
        factors.append(f"Dự báo DO chạm ngưỡng nguy cấp ({predicted_do:.2f} mg/L)")

    # 3. Dự báo xu hướng pH
    # pH thường biến thiên nhẹ theo quang hợp/hô hấp
    predicted_ph = round(ph + 0.05 if ph < 8.0 else ph - 0.05, 2)
    if ph < 7.5 or ph > 8.5:
        risk_points += 20.0
        factors.append(f"Độ pH {ph:.2f} ngoài khoảng lý tưởng (7.5 - 8.5)")
    else:
        factors.append(f"Độ pH {ph:.2f} trong ngưỡng tối ưu")

    # 4. Tác động của nhiệt độ
    if temp > 33.0:
        risk_points += 15.0
        factors.append(f"Nhiệt độ nước cao {temp:.1f}°C làm tăng tốc độ tiêu thụ oxy")
    elif temp < 24.0:
        risk_points += 10.0
        factors.append(f"Nhiệt độ nước lạnh {temp:.1f}°C")

    # Giới hạn điểm rủi ro từ 0 đến 100
    risk_score = min(100.0, max(0.0, risk_points))

    # Xác định cấp độ rủi ro theo chuẩn NestJS
    if risk_score >= 65.0:
        risk_level = NestJSRiskLevel.DANGER
        alert = True
    elif risk_score >= 35.0:
        risk_level = NestJSRiskLevel.WARNING
        alert = True
    else:
        risk_level = NestJSRiskLevel.SAFE
        alert = False

    return round(predicted_do, 2), predicted_ph, round(risk_score, 1), risk_level, alert, factors


@router.post(
    "/predict",
    response_model=NestJSPredictResponse,
    status_code=status.HTTP_200_OK,
    summary="Dự báo chất lượng nước (Tương thích NestJS PredictionsService)",
    description="Nhận telemetry và trả về predictedDO, predictedPH, riskScore, riskLevel, alert, factors.",
)
async def predict_water_quality(
    request: NestJSPredictRequest,
    redis_cache: RedisCacheService = Depends(get_redis_cache),
) -> NestJSPredictResponse:
    """
    Endpoint tương thích 100% với Core Backend NestJS PredictionsService.
    Tự động đồng bộ kết quả vào Redis Cache với TTL 1800s.
    """
    pred_do, pred_ph, risk_score, risk_level, alert, factors = compute_water_quality_forecast(request)

    logger.info(
        f"[NestJS Predict] Ao: {request.pond_id} | DO: {request.current_do} -> PredDO: {pred_do} | "
        f"Score: {risk_score} | Level: {risk_level.value} | Alert: {alert}"
    )

    response_data = NestJSPredictResponse(
        predictedDO=pred_do,
        predictedPH=pred_ph,
        riskScore=risk_score,
        riskLevel=risk_level,
        alert=alert,
        factors=factors,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    # Lưu kết quả vào Redis cache bất đồng bộ nếu có pond_id
    if request.pond_id:
        await redis_cache.set_water_quality_forecast(request.pond_id, response_data.model_dump())

    return response_data


@router.get(
    "/predict/{pond_id}/latest",
    response_model=NestJSPredictResponse,
    status_code=status.HTTP_200_OK,
    summary="Lấy kết quả dự báo chất lượng nước mới nhất từ Redis Cache",
    description="Truy xuất nhanh kết quả dự báo chất lượng nước trong < 5ms cho Web Portal và Mobile App.",
)
async def get_latest_water_quality_prediction(
    pond_id: str,
    redis_cache: RedisCacheService = Depends(get_redis_cache),
) -> NestJSPredictResponse:
    """
    Truy xuất kết quả dự báo chất lượng nước mới nhất từ Redis Cache
    """
    cached = await redis_cache.get_water_quality_forecast(pond_id)
    if not cached:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chưa có dữ liệu dự báo chất lượng nước trong cache cho ao: {pond_id}",
        )
    return NestJSPredictResponse(**cached)

