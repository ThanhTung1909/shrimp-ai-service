"""
Test suite cho TASK-ML-03: AI Soft Sensor Benson & Krause (1984) và Quỹ đạo Oxy Đêm
"""

import pytest
from app.models.soft_sensor import (
    calculate_do_saturation,
    analyze_do_saturation_status,
    predict_nighttime_do_depletion,
)


def test_benson_krause_usgs_benchmark_values():
    """
    Kiểm định độ chính xác phương trình nhiệt động học Benson & Krause (1984)
    đối chiếu trực tiếp với Bảng chuẩn Thủy văn Quốc tế (USGS Field Manual & Standard Methods 21st ed).
    Sai số cho phép < 0.5%.
    """
    benchmarks = [
        # (Nhiệt độ °C, Độ mặn ppt, Giá trị chuẩn phương trình Benson & Krause 1984 mg/L)
        (20.0, 0.0, 9.092),
        (25.0, 0.0, 8.263),
        (25.0, 15.0, 7.588),
        (30.0, 25.0, 6.589),
        (32.0, 20.0, 6.529),
    ]

    for temp, sal, expected in benchmarks:
        computed = calculate_do_saturation(temp, sal)
        diff_percent = abs(computed - expected) / expected * 100.0
        print(f"T={temp}°C, S={sal}ppt -> Computed: {computed}, USGS: {expected}, Diff: {diff_percent:.3f}%")
        assert diff_percent < 0.5, f"Độ lệch tại T={temp}, S={sal} vượt quá 0.5%: {diff_percent:.3f}%"
        assert pytest.approx(computed, abs=0.03) == expected


def test_benson_krause_boundary_validation():
    """Kiểm tra xử lý biên của hàm tính bão hòa oxy"""
    # Nhiệt độ âm hoặc quá 50°C
    with pytest.raises(ValueError, match="Nhiệt độ ngoài dải"):
        calculate_do_saturation(-5.0, 10.0)

    # Độ mặn âm hoặc quá 50 ppt
    with pytest.raises(ValueError, match="Độ mặn ngoài dải"):
        calculate_do_saturation(28.0, -2.0)


def test_analyze_do_saturation_status_classes():
    """Kiểm tra phân loại trạng thái bão hòa oxy ao tôm"""
    # 1. Bão hòa tối ưu (T=28, S=15 -> DO_sat ~ 7.2 mg/L, measured = 6.8 mg/L -> ~94%)
    opt_res = analyze_do_saturation_status(28.0, 15.0, 6.8)
    assert opt_res["status"] == "OPTIMAL"
    assert opt_res["saturation_percentage"] > 90.0

    # 2. Quá bão hòa do tảo quang hợp mạnh giữa trưa (measured = 10.0 mg/L)
    over_res = analyze_do_saturation_status(28.0, 15.0, 10.0)
    assert over_res["status"] == "OVERSATURATED"

    # 3. Thiếu oxy nghiêm trọng (measured = 2.5 mg/L -> < 40%)
    crit_res = analyze_do_saturation_status(28.0, 15.0, 2.5)
    assert crit_res["status"] == "CRITICAL"
    assert "ngạt khí" in crit_res["action_suggestion"]


def test_nighttime_do_depletion_prediction():
    """Kiểm tra mô hình dự báo suy giảm oxy ban đêm và cảnh báo rủi ro ngạt tôm"""
    # Kịch bản 1: Chiều tối đo được 4.0 mg/L lúc 18:00, không chạy quạt nước
    # Sau 8 tiếng qua đêm, DO sẽ giảm sâu < 3.0 mg/L -> Cảnh báo HIGH
    pred_res = predict_nighttime_do_depletion(
        current_temp=29.0,
        salinity=15.0,
        current_do=4.0,
        hours_ahead=8,
        aeration_active=False,
    )

    assert "trajectory" in pred_res
    assert len(pred_res["trajectory"]) == 8
    assert pred_res["risk_level"] == "HIGH"
    assert pred_res["minimum_projected_do"] < 3.0
    assert "NGUY CƠ CAO" in pred_res["alert_message"]

    # Kịch bản 2: Bật quạt nước (aeration_active=True) giúp giảm tốc độ suy giảm
    pred_with_aeration = predict_nighttime_do_depletion(
        current_temp=29.0,
        salinity=15.0,
        current_do=5.5,
        hours_ahead=8,
        aeration_active=True,
    )

    assert pred_with_aeration["minimum_projected_do"] > pred_res["minimum_projected_do"]
    assert pred_with_aeration["risk_level"] in ("LOW", "MEDIUM")
