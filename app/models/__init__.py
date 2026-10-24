"""
AquaSense AI Models Package
Chứa mô hình học máy XGBoost Feeding, AI Soft Sensor Benson & Krause (1984),
và Động cơ Đánh giá Chất lượng Nước Đa Thông số (Aquaculture Water Quality Engine).
"""

from app.models.soft_sensor import (
    analyze_do_saturation_status,
    benson_krause_do_saturation,
    calculate_do_saturation,
    predict_nighttime_do_depletion,
)
from app.models.water_quality import (
    calculate_shrimp_wqi,
    calculate_toxic_ammonia_nh3,
    evaluate_dissolved_oxygen,
    evaluate_nitrite_toxicity,
    evaluate_orp,
    evaluate_ph,
    evaluate_salinity,
    evaluate_temperature,
    evaluate_turbidity,
)
from app.models.xgboost_feeding import (
    FeedingModelTrainer,
    XGBoostFeedingTrainer,
    load_trained_feeding_model,
)

__all__ = [
    "benson_krause_do_saturation",
    "calculate_do_saturation",
    "analyze_do_saturation_status",
    "predict_nighttime_do_depletion",
    "calculate_toxic_ammonia_nh3",
    "evaluate_dissolved_oxygen",
    "evaluate_ph",
    "evaluate_temperature",
    "evaluate_salinity",
    "evaluate_nitrite_toxicity",
    "evaluate_orp",
    "evaluate_turbidity",
    "calculate_shrimp_wqi",
    "FeedingModelTrainer",
    "XGBoostFeedingTrainer",
    "load_trained_feeding_model",
]
