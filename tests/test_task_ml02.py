"""
Test suite cho TASK-ML-02: Đánh giá độ chính xác và cam kết chuẩn khoa học (R2 >= 0.78, MAPE <= 8.7%)
"""

import numpy as np
import pytest
from app.data.generate_synthetic_data import generate_synthetic_feeding_dataset
from app.models.xgboost_feeding import (
    evaluate_model,
    validate_scientific_acceptance,
    train_and_validate_feeding_model,
)


def test_evaluate_model_metrics_calculation():
    """Kiểm tra độ chính xác của hàm tính toán 4 chỉ số đo lường hiệu năng"""
    y_true = np.array([10.0, 20.0, 30.0, 40.0, 50.0])
    y_pred = np.array([10.5, 19.5, 30.0, 41.0, 49.0])

    metrics = evaluate_model(y_true, y_pred)

    assert "r2" in metrics
    assert "mape" in metrics
    assert "mae" in metrics
    assert "rmse" in metrics

    # Sai số thực tế rất nhỏ -> R2 phải gần 1.0, MAPE < 3%
    assert metrics["r2"] > 0.98
    assert metrics["mape"] < 3.0
    assert metrics["mae"] == 0.6
    assert pytest.approx(metrics["rmse"], 0.05) == 0.74


def test_validate_scientific_acceptance_thresholds():
    """Kiểm tra hàm assert chuẩn khoa học: R2 >= 0.78 và MAPE <= 8.7%"""
    # 1. Thỏa mãn cả 2 tiêu chí -> Thành công
    good_metrics = {"r2": 0.85, "mape": 6.5, "mae": 2.1, "rmse": 2.8}
    assert validate_scientific_acceptance(good_metrics, min_r2=0.78, max_mape=8.7) is True

    # 2. R2 dưới 0.78 -> Báo lỗi
    bad_r2_metrics = {"r2": 0.75, "mape": 7.0, "mae": 3.0, "rmse": 3.8}
    with pytest.raises(ValueError, match="R²=0.7500"):
        validate_scientific_acceptance(bad_r2_metrics, min_r2=0.78, max_mape=8.7)

    # 3. MAPE vượt quá 8.7% -> Báo lỗi
    bad_mape_metrics = {"r2": 0.82, "mape": 9.5, "mae": 4.0, "rmse": 4.5}
    with pytest.raises(ValueError, match="MAPE=9.50%"):
        validate_scientific_acceptance(bad_mape_metrics, min_r2=0.78, max_mape=8.7)


def test_end_to_end_model_meets_scientific_standards(tmp_path):
    """
    Kiểm định khoa học cốt lõi của dự án (Core Scientific Benchmark):
    Huấn luyện mô hình XGBoost với 600 estimators, lr=0.05, max_depth=6
    trên bộ dữ liệu thực nghiệm chuẩn và xác minh trên tập test độc lập:
    - R² >= 0.78
    - MAPE <= 8.7%
    """
    df = generate_synthetic_feeding_dataset(num_ponds=10, cycle_days=90, random_seed=42)
    scaler_file = tmp_path / "feeding_scaler.joblib"

    trainer, metrics = train_and_validate_feeding_model(
        df=df,
        test_ratio=0.20,
        assert_acceptance=True,
        scaler_path=str(scaler_file),
    )

    print(f"\n[Test Result] R² = {metrics['r2']:.4f}, MAPE = {metrics['mape']:.2f}%")
    assert metrics["r2"] >= 0.78, f"R² đạt {metrics['r2']:.4f}, không thỏa mãn >= 0.78"
    assert metrics["mape"] <= 8.7, f"MAPE đạt {metrics['mape']:.2f}%, không thỏa mãn <= 8.7%"
