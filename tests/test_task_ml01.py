"""
Test suite cho TASK-ML-01: Cấu hình và Huấn luyện mô hình XGBoost Feeding
"""

import numpy as np
import pytest
from app.data.generate_synthetic_data import generate_synthetic_feeding_dataset
from app.models.xgboost_feeding import (
    DEFAULT_XGBOOST_PARAMS,
    XGBoostFeedingTrainer,
)
from app.services.pipeline import (
    REQUIRED_FEEDING_FEATURES,
    TimeSeriesDataPipeline,
)


def test_default_xgboost_hyperparameters():
    """Kiểm tra bộ siêu tham số thực nghiệm bắt buộc của XGBoost"""
    assert DEFAULT_XGBOOST_PARAMS["n_estimators"] == 600
    assert DEFAULT_XGBOOST_PARAMS["learning_rate"] == 0.05
    assert DEFAULT_XGBOOST_PARAMS["max_depth"] == 6
    assert DEFAULT_XGBOOST_PARAMS["subsample"] == 0.8
    assert DEFAULT_XGBOOST_PARAMS["colsample_bytree"] == 0.8
    assert DEFAULT_XGBOOST_PARAMS["random_state"] == 42


def test_trainer_build_and_train(tmp_path):
    """Kiểm tra khởi tạo và huấn luyện mô hình với 7 biến thực nghiệm"""
    df = generate_synthetic_feeding_dataset(num_ponds=2, cycle_days=30, random_seed=42)

    # Sử dụng TimeSeriesDataPipeline chuẩn bị dữ liệu train/test
    scaler_file = tmp_path / "feeding_scaler.joblib"
    pipeline = TimeSeriesDataPipeline(scaler_path=str(scaler_file))
    X_train_s, y_train, X_test_s, y_test, _ = pipeline.prepare_time_blocked_split(
        df, test_ratio=0.20, save_scaler=True
    )

    trainer = XGBoostFeedingTrainer(
        scaler_path=str(scaler_file),
    )
    trainer.build_model()
    model = trainer.train(X_train_s, y_train)

    assert model is not None
    # Kiểm tra dự báo
    preds = trainer.predict(X_test_s, is_scaled=True)
    assert len(preds) == len(y_test)
    assert np.all(preds >= 0.5)

    # Kiểm tra trích xuất Feature Importances
    importances = trainer.get_feature_importances()
    for feat in REQUIRED_FEEDING_FEATURES:
        assert feat in importances
        assert isinstance(importances[feat], float)


def test_trainer_predict_raw_inputs(tmp_path):
    """Kiểm tra dự báo từ dữ liệu thô (chưa scale) tự động sử dụng scaler đã nạp"""
    df = generate_synthetic_feeding_dataset(num_ponds=1, cycle_days=20, random_seed=99)
    scaler_file = tmp_path / "feeding_scaler.joblib"
    pipeline = TimeSeriesDataPipeline(scaler_path=str(scaler_file))
    X_train_s, y_train, _, _, _ = pipeline.prepare_time_blocked_split(df, test_ratio=0.2, save_scaler=True)

    trainer = XGBoostFeedingTrainer(scaler_path=str(scaler_file))
    trainer.train(X_train_s, y_train)

    # Test single sample: 7 biến thực nghiệm thô
    raw_sample = [45.0, 15.0, 5.2, 0.05, 0.0, 35.0, 10.0]
    pred = trainer.predict(raw_sample, is_scaled=False)
    assert len(pred) == 1
    assert pred[0] > 0.5


def test_trainer_invalid_feature_count(tmp_path):
    """Kiểm tra bắt lỗi nếu đầu vào thiếu hoặc thừa số lượng đặc trưng"""
    df = generate_synthetic_feeding_dataset(num_ponds=1, cycle_days=10, random_seed=1)
    scaler_file = tmp_path / "feeding_scaler.joblib"
    pipeline = TimeSeriesDataPipeline(scaler_path=str(scaler_file))
    X_train_s, y_train, _, _, _ = pipeline.prepare_time_blocked_split(df, test_ratio=0.2, save_scaler=True)

    trainer = XGBoostFeedingTrainer(scaler_path=str(scaler_file))
    trainer.train(X_train_s, y_train)

    # Chỉ truyền 5 biến thay vì 7 biến
    with pytest.raises(ValueError, match="Số lượng đặc trưng không khớp"):
        trainer.predict(np.array([[45.0, 15.0, 5.2, 0.05, 0.0]]), is_scaled=True)
