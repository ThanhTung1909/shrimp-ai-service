"""
REST API Endpoint: Dự báo lượng thức ăn cho tôm và đánh giá rủi ro bỏ ăn.
POST /api/v1/ai/forecast-feeding
Tuân thủ Inference Latency Rule (< 500ms) và Feature Integrity Rule (7 biến bắt buộc).
Do Backend-Integration-Agent chủ trì.
"""

from datetime import datetime, timezone
import logging
import time
from typing import Dict, Tuple
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import (
    get_feeding_trainer,
    get_rabbitmq_publisher,
    get_redis_cache,
)
from app.models.xgboost_feeding import XGBoostFeedingTrainer
from app.schemas.feeding import (
    FeedingForecastRequest,
    FeedingForecastResponse,
    FeedingRiskLevel,
)
from app.services.rabbitmq_publisher import RabbitMQPublisher
from app.services.redis_cache import RedisCacheService

logger = logging.getLogger("ai_service.api.feeding")

router = APIRouter(prefix="/ai", tags=["Feeding Forecast"])


def analyze_feeding_risk_and_recommendation(
    req: FeedingForecastRequest,
    raw_feed_kg: float,
) -> Tuple[float, FeedingRiskLevel, Dict[str, str], str]:
    """
    Phân tích rủi ro môi trường và điều chỉnh lượng thức ăn phù hợp:
    1. Lượng mưa lúc 06:00 sáng (rain_0600): Gây sốc nhiệt, tụt độ mặn/pH khiến tôm bỏ ăn.
    2. Oxy hòa tan tối thiểu (do_min): Dưới 3.5 mg/L tôm bị ngạt, ngừng ăn.
    3. Biến thiên tổng amoniac (tan_delta): Khí độc tích tụ gây ngộ độc.
    """
    adjusted_feed = raw_feed_kg
    factors: Dict[str, str] = {}
    risk_level = FeedingRiskLevel.LOW
    notes: list[str] = []

    # 1. Tác động của mưa sáng 06:00
    if req.rain_0600 >= 50.0:
        risk_level = FeedingRiskLevel.CRITICAL
        adjusted_feed *= 0.60
        factors["rain_0600"] = f"Mưa cực lớn {req.rain_0600}mm gây sốc môi trường nghiêm trọng (giảm 40% cữ ăn)."
        notes.append("Tôm sốc nước mưa lớn, giảm 40% thức ăn; tạt vôi nông nghiệp và khoáng chống sốc.")
    elif req.rain_0600 >= 20.0:
        if risk_level != FeedingRiskLevel.CRITICAL:
            risk_level = FeedingRiskLevel.HIGH
        adjusted_feed *= 0.75
        factors["rain_0600"] = f"Mưa lớn {req.rain_0600}mm lúc 06:00 gây lạnh nước và giảm oxy bề mặt (giảm 25% cữ ăn)."
        notes.append("Giảm 25% khẩu phần; kiểm tra độ kiềm và pH ngay sau khi tạnh mưa.")
    elif req.rain_0600 >= 5.0:
        if risk_level == FeedingRiskLevel.LOW:
            risk_level = FeedingRiskLevel.MEDIUM
        adjusted_feed *= 0.90
        factors["rain_0600"] = f"Mưa nhỏ đến vừa {req.rain_0600}mm (giảm 10% cữ ăn)."
        notes.append("Giảm nhẹ 10% lượng thức ăn cữ sáng.")
    else:
        factors["rain_0600"] = "Không có mưa sáng đáng kể, sức ăn không bị ảnh hưởng bởi thời tiết."

    # 2. Tác động của Oxy hòa tan tối thiểu (do_min)
    if req.do_min < 3.0:
        risk_level = FeedingRiskLevel.CRITICAL
        adjusted_feed *= 0.50
        factors["do_min"] = f"DO tối thiểu cực nguy hiểm {req.do_min} mg/L (< 3.0 mg/L) - tôm ngạt khí."
        notes.append("Oxy hòa tan chạm đáy nguy cấp! Cắt 50% thức ăn, bật toàn bộ quạt nước và cấp oxy viên cấp cứu.")
    elif req.do_min < 3.8:
        if risk_level != FeedingRiskLevel.CRITICAL:
            risk_level = FeedingRiskLevel.HIGH
        adjusted_feed *= 0.80
        factors["do_min"] = f"DO tối thiểu thấp {req.do_min} mg/L (ngưỡng an toàn >= 4.0 mg/L)."
        notes.append("Oxy hòa tan thấp; giảm 20% thức ăn và tăng cường chạy quạt trước khi cho ăn.")
    elif req.do_min < 4.2:
        if risk_level == FeedingRiskLevel.LOW:
            risk_level = FeedingRiskLevel.MEDIUM
        factors["do_min"] = f"DO tối thiểu ở mức chấp nhận được {req.do_min} mg/L."
    else:
        factors["do_min"] = f"DO tối thiểu tốt {req.do_min} mg/L, đảm bảo quá trình tiêu hóa tối ưu."

    # 3. Tác động của Biến thiên Amoniac (tan_delta)
    if req.tan_delta >= 0.5:
        if risk_level in [FeedingRiskLevel.LOW, FeedingRiskLevel.MEDIUM]:
            risk_level = FeedingRiskLevel.HIGH
        adjusted_feed *= 0.85
        factors["tan_delta"] = f"Tổng amoniac tăng vọt +{req.tan_delta} mg/L, nguy cơ ô nhiễm đáy ao."
        notes.append("Khí độc TAN tăng nhanh; giảm 15% thức ăn, bổ sung men vi sinh xử lý đáy ao.")
    elif req.tan_delta >= 0.2:
        if risk_level == FeedingRiskLevel.LOW:
            risk_level = FeedingRiskLevel.MEDIUM
        factors["tan_delta"] = f"TAN tăng nhẹ +{req.tan_delta} mg/L."
    else:
        factors["tan_delta"] = f"Chỉ số amoniac ổn định (biến thiên {req.tan_delta:+.2f} mg/L)."

    # 4. Tỷ lệ thay nước (water_exchange_ratio)
    if req.water_exchange_ratio >= 30.0:
        notes.append(f"Ao vừa thay {req.water_exchange_ratio}% nước; theo dõi sự thích nghi của tôm.")

    # Đảm bảo lượng thức ăn sinh học tối thiểu >= 0.5 kg
    final_feed = max(0.5, round(adjusted_feed, 2))
    recommendation_note = " | ".join(notes) if notes else "Môi trường ao nuôi ổn định, duy trì cữ ăn bình thường."

    return final_feed, risk_level, factors, recommendation_note


@router.post(
    "/forecast-feeding",
    response_model=FeedingForecastResponse,
    status_code=status.HTTP_200_OK,
    summary="Dự báo lượng thức ăn cho tôm và phân tích rủi ro",
    description="Tiếp nhận 7 biến thực nghiệm bắt buộc, trả về lượng thức ăn khuyến nghị và cảnh báo rủi ro trong < 500ms.",
)
async def forecast_feeding(
    request: FeedingForecastRequest,
    trainer: XGBoostFeedingTrainer = Depends(get_feeding_trainer),
    redis_cache: RedisCacheService = Depends(get_redis_cache),
    rabbitmq: RabbitMQPublisher = Depends(get_rabbitmq_publisher),
) -> FeedingForecastResponse:
    """
    Endpoint dự báo lượng thức ăn với độ trễ siêu thấp (< 50ms trong RAM).
    Tự động đồng bộ kết quả vào Redis Cache với TTL 1800s.
    Tự động xuất bản sự kiện ai.risk.detected sang RabbitMQ khi rủi ro ở mức HIGH/CRITICAL.
    """
    t0 = time.perf_counter()

    try:
        # 1. Trích xuất đúng 7 biến thực nghiệm
        features = request.to_feature_list()

        # 2. Suy luận lượng thức ăn thô qua XGBoost đã nạp trong RAM
        raw_pred = trainer.predict(features, is_scaled=False)
        predicted_kg = float(raw_pred[0])

        # 3. Phân tích rủi ro môi trường và điều chỉnh sinh học
        recommended_feed, risk_level, factors, note = analyze_feeding_risk_and_recommendation(
            request, predicted_kg
        )

        # 4. Tính toán độ trễ suy luận
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        # Đánh giá độ tin cậy dựa trên tính ổn định môi trường
        confidence = 0.96 if risk_level == FeedingRiskLevel.LOW else (
            0.92 if risk_level == FeedingRiskLevel.MEDIUM else 0.88
        )

        logger.info(
            f"[Feeding Forecast] Ao: {request.pond_id} | Raw: {predicted_kg:.2f}kg -> "
            f"Rec: {recommended_feed:.2f}kg | Risk: {risk_level.value} | Latency: {latency_ms}ms"
        )

        response_data = FeedingForecastResponse(
            pond_id=request.pond_id,
            recommended_feed_kg=recommended_feed,
            risk_level=risk_level,
            confidence_score=confidence,
            factors_impact=factors,
            recommendation_note=note,
            model_version="1.0.0",
            latency_ms=latency_ms,
            computed_at=datetime.now(timezone.utc).isoformat(),
        )

        # 5. Lưu kết quả vào Redis cache bất đồng bộ (không block nếu offline)
        if request.pond_id:
            await redis_cache.set_feeding_forecast(request.pond_id, response_data.model_dump())

        # 6. Đẩy sự kiện cảnh báo sớm vào RabbitMQ khi phát hiện nguy cơ cao (Task-BE-05)
        if risk_level in (FeedingRiskLevel.HIGH, FeedingRiskLevel.CRITICAL) and request.pond_id:
            await rabbitmq.publish_risk_alert(
                pond_id=request.pond_id,
                risk_level=risk_level.value,
                metric="feeding_intake",
                predicted_value=recommended_feed,
                action_suggestion=note,
                details=factors,
            )

        return response_data

    except Exception as e:
        logger.error(f"[Feeding Forecast Error] {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Lỗi suy luận mô hình dự báo thức ăn: {str(e)}",
        )


@router.get(
    "/forecast-feeding/{pond_id}/latest",
    response_model=FeedingForecastResponse,
    status_code=status.HTTP_200_OK,
    summary="Lấy kết quả dự báo lượng thức ăn mới nhất từ Redis Cache",
    description="Truy xuất nhanh kết quả dự báo trong < 5ms cho Web Portal và Mobile App.",
)
async def get_latest_feeding_forecast(
    pond_id: str,
    redis_cache: RedisCacheService = Depends(get_redis_cache),
) -> FeedingForecastResponse:
    """
    Truy xuất kết quả dự báo thức ăn mới nhất từ Redis Cache
    """
    cached = await redis_cache.get_feeding_forecast(pond_id)
    if not cached:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chưa có dữ liệu dự báo được lưu trong cache cho ao: {pond_id}",
        )
    return FeedingForecastResponse(**cached)

