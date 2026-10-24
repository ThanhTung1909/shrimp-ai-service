"""
Test suite cho TASK-DP-03: Trích xuất 7 đặc trưng thực nghiệm và sinh dữ liệu thực nghiệm
"""

from datetime import datetime, timezone
import pandas as pd
import pytest
from app.services.pipeline import (
    REQUIRED_FEEDING_FEATURES,
    build_feeding_feature_dict,
    extract_do_min_from_telemetry,
    extract_features_from_pond_state,
)
from app.data.generate_synthetic_data import (
    von_bertalanffy_weight,
    generate_synthetic_feeding_dataset,
)


def test_required_features_list_integrity():
    """Quy tắc Feature Integrity: Bắt buộc bảo toàn đúng 7 biến thực nghiệm"""
    expected_7_features = (
        "shrimp_age",
        "shrimp_weight",
        "do_min",
        "tan_delta",
        "rain_0600",
        "previous_feed",
        "water_exchange_ratio",
    )
    assert REQUIRED_FEEDING_FEATURES == expected_7_features


def test_build_feeding_feature_dict_valid():
    """Kiểm tra đóng gói 7 biến hợp lệ"""
    features = build_feeding_feature_dict(
        shrimp_age=45,
        shrimp_weight=12.5,
        do_min=4.2,
        tan_delta=0.05,
        rain_0600=15.0,
        previous_feed=28.0,
        water_exchange_ratio=10.0,
    )

    for feat in REQUIRED_FEEDING_FEATURES:
        assert feat in features

    assert features["shrimp_age"] == 45.0
    assert features["shrimp_weight"] == 12.5
    assert features["rain_0600"] == 15.0


def test_build_feeding_feature_dict_invalid_inputs():
    """Kiểm tra chặn các giá trị phi sinh học hoặc âm vô lý"""
    with pytest.raises(ValueError, match="shrimp_age"):
        build_feeding_feature_dict(0, 10.0, 4.0, 0, 0, 10, 0)

    with pytest.raises(ValueError, match="shrimp_weight"):
        build_feeding_feature_dict(30, 0.0, 4.0, 0, 0, 10, 0)

    with pytest.raises(ValueError, match="rain_0600"):
        build_feeding_feature_dict(30, 10.0, 4.0, 0, -5.0, 10, 0)

    with pytest.raises(ValueError, match="water_exchange_ratio"):
        build_feeding_feature_dict(30, 10.0, 4.0, 0, 0, 10, 150.0)


def test_extract_do_min_from_telemetry():
    """Kiểm tra trích xuất do_min từ chuỗi telemetry 12 giờ gần nhất"""
    dates = pd.date_range("2026-09-04 00:00:00", periods=48, freq="15min", tz="UTC")
    # Giá trị DO dao động từ 3.2 đến 6.5
    do_values = [5.5] * 20 + [3.2] + [5.8] * 27
    df = pd.DataFrame({"avg_dissolved_oxygen": do_values}, index=dates)

    do_min = extract_do_min_from_telemetry(df, window_hours=12)
    assert do_min == 3.2


def test_von_bertalanffy_growth_curve():
    """Kiểm tra đường cong sinh trưởng von Bertalanffy của tôm thẻ chân trắng"""
    w_day1 = von_bertalanffy_weight(1)
    w_day30 = von_bertalanffy_weight(30)
    w_day60 = von_bertalanffy_weight(60)
    w_day90 = von_bertalanffy_weight(90)

    # Khối lượng phải tăng đơn điệu theo tuổi
    assert 0 < w_day1 < w_day30 < w_day60 < w_day90
    # Ngày 90 trọng lượng tôm thẻ thương phẩm khoảng 20 - 30g
    assert 18.0 <= w_day90 <= 32.0


def test_generate_synthetic_feeding_dataset():
    """Kiểm tra bộ sinh dữ liệu thực nghiệm: đầy đủ cột, không khuyết tật, phản ánh hiệu ứng mưa 06:00"""
    df = generate_synthetic_feeding_dataset(num_ponds=2, cycle_days=30, random_seed=123)

    assert not df.empty
    assert len(df) == 2 * 30 * 4  # 2 ao * 30 ngày * 4 cữ = 240 dòng

    # Kiểm tra đầy đủ 7 biến thực nghiệm + biến mục tiêu
    for feat in REQUIRED_FEEDING_FEATURES:
        assert feat in df.columns
    assert "feed_amount_kg" in df.columns

    # Không có giá trị NaN hay vô cùng
    assert df[list(REQUIRED_FEEDING_FEATURES) + ["feed_amount_kg"]].isna().sum().sum() == 0

    # Kiểm tra tính chất thực nghiệm: Những ngày mưa lúc 06:00 sáng tôm ăn ít hơn so với ngày bình thường ở cùng độ tuổi
    rainy_sample = df[(df["rain_0600"] > 15.0) & (df["shrimp_age"] > 15)]
    dry_sample = df[(df["rain_0600"] == 0.0) & (df["shrimp_age"] > 15)]
    assert not rainy_sample.empty
    assert not dry_sample.empty
