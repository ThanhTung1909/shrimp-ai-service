"""
Unit tests cho TASK-ML-04: Đóng gói và xuất file trọng số mô hình (.joblib) kèm model_metadata.json
Do ML-Modeling-Agent và DevOps-Infrastructure-Agent phối hợp kiểm định.
"""

import json
from pathlib import Path
import time
import numpy as np
import pytest

from app.models.xgboost_feeding import (
    XGBoostFeedingTrainer,
    load_trained_feeding_model,
)
from app.services.pipeline import REQUIRED_FEEDING_FEATURES


@pytest.fixture
def trained_artifacts_dir():
    return Path("trained_models")


def test_saved_artifacts_exist(trained_artifacts_dir):
    """Kiểm tra các file artifacts bắt buộc đã được sinh ra trên đĩa"""
    model_file = trained_artifacts_dir / "xgboost_feeding_model.joblib"
    scaler_file = trained_artifacts_dir / "feeding_scaler.joblib"
    metadata_file = trained_artifacts_dir / "model_metadata.json"

    assert model_file.exists(), f"Không tìm thấy file trọng số {model_file}"
    assert scaler_file.exists(), f"Không tìm thấy file scaler {scaler_file}"
    assert metadata_file.exists(), f"Không tìm thấy file metadata {metadata_file}"

    # Kiểm tra kích thước file
    assert model_file.stat().st_size > 100_000, "File model trọng số quá nhỏ"
    assert metadata_file.stat().st_size > 200, "File metadata quá nhỏ"


def test_metadata_schema_and_values(trained_artifacts_dir):
    """Kiểm tra cấu trúc và tính hợp lệ của model_metadata.json"""
    metadata_file = trained_artifacts_dir / "model_metadata.json"
    with open(metadata_file, "r", encoding="utf-8") as f:
        meta = json.load(f)

    # 1. Thông tin chung
    assert meta["model_name"] == "xgboost_feeding_model"
    assert meta["version"] == "1.0.0"
    assert meta["model_type"] == "XGBRegressor"
    assert "trained_at" in meta

    # 2. Feature Integrity (7 biến thực nghiệm)
    feat_meta = meta["feature_integrity"]
    assert feat_meta["count"] == 7
    assert tuple(feat_meta["features"]) == REQUIRED_FEEDING_FEATURES
    assert feat_meta["target"] == "feed_amount_kg"

    # 3. Hyperparameters
    params = meta["hyperparameters"]
    assert params["n_estimators"] == 600
    assert params["learning_rate"] == 0.05
    assert params["max_depth"] == 6
    assert params["subsample"] == 0.8
    assert params["colsample_bytree"] == 0.8

    # 4. Metrics & Tiêu chuẩn khoa học
    metrics = meta["metrics"]
    assert metrics["r2"] >= 0.78, f"R² metadata {metrics['r2']} < 0.78"
    assert metrics["mape"] <= 8.7, f"MAPE metadata {metrics['mape']}% > 8.7%"

    assert meta["scientific_acceptance"]["passed"] is True
    assert meta["scientific_acceptance"]["min_r2_threshold"] == 0.78
    assert meta["scientific_acceptance"]["max_mape_threshold"] == 8.7

    # 5. Feature importances có đủ 7 biến
    importances = meta["feature_importances"]
    assert len(importances) == 7
    for feat in REQUIRED_FEEDING_FEATURES:
        assert feat in importances
        assert importances[feat] >= 0.0


def test_load_model_and_predict():
    """Kiểm tra nạp lại mô hình từ đĩa và dự báo chính xác qua load_trained_feeding_model"""
    trainer = load_trained_feeding_model(
        model_path="trained_models/xgboost_feeding_model.joblib",
        scaler_path="trained_models/feeding_scaler.joblib",
        metadata_path="trained_models/model_metadata.json",
    )
    assert trainer.model is not None

    # Mẫu test thực tế: ngày 45, tôm 14.5g, do_min=4.2 mg/L, tan_delta=0.05, rain=0.0mm, cữ trước=25kg, thay nước=0%
    sample = [45, 14.5, 4.2, 0.05, 0.0, 25.0, 0.0]
    pred = trainer.predict(sample, is_scaled=False)

    assert isinstance(pred, np.ndarray)
    assert pred.shape == (1,)
    feed_pred = float(pred[0])
    # Với tôm 45 ngày tuổi, sinh khối ~2.1 tấn, 1 cữ ăn ~35-40kg, dự báo nên nằm trong khoảng 20-50kg
    assert 20.0 <= feed_pred <= 50.0, f"Dự báo bất thường: {feed_pred} kg"


def test_inference_latency_under_500ms():
    """
    Quy tắc Độ trễ (Inference Latency Rule):
    API suy luận của AI Service phải đạt thời gian phản hồi < 500 ms.
    Với model nạp sẵn trong RAM, latency một lần suy luận phải < 10 ms.
    """
    trainer = load_trained_feeding_model()
    sample = [45, 14.5, 4.2, 0.05, 0.0, 25.0, 0.0]

    # Warm-up 5 lần
    for _ in range(5):
        trainer.predict(sample, is_scaled=False)

    # Đo thời gian 50 lần suy luận
    latencies = []
    for _ in range(50):
        t0 = time.perf_counter()
        trainer.predict(sample, is_scaled=False)
        latencies.append((time.perf_counter() - t0) * 1000.0)  # ms

    avg_latency = float(np.mean(latencies))
    max_latency = float(np.max(latencies))

    assert avg_latency < 20.0, f"Độ trễ trung bình quá cao: {avg_latency:.2f} ms (yêu cầu < 20 ms)"
    assert max_latency < 500.0, f"Độ trễ tối đa vi phạm quy tắc < 500ms: {max_latency:.2f} ms"


def test_load_model_file_not_found(tmp_path):
    """Kiểm tra exception khi tải mô hình từ đường dẫn không tồn tại"""
    fake_path = tmp_path / "non_existent_model.joblib"
    trainer = XGBoostFeedingTrainer(model_path=str(fake_path))
    with pytest.raises(FileNotFoundError):
        trainer.load_model()
