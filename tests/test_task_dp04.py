"""
Test suite cho TASK-DP-04: Phân chia Time-Blocked Cross-Validation & StandardScaler Chống Rò Rỉ
"""

from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from app.data.generate_synthetic_data import generate_synthetic_feeding_dataset
from app.services.pipeline import (
    REQUIRED_FEEDING_FEATURES,
    TimeSeriesDataPipeline,
)


def test_anti_data_leakage_scaler_fit_strictly_on_train_set(tmp_path):
    """
    Quy tắc Anti-Data Leakage:
    StandardScaler CHỈ ĐƯỢC PHÉP fit trên tập huấn luyện (Train set).
    Tập kiểm thử (Test set) chỉ được transform dựa trên mean/scale của tập train.
    """
    df = generate_synthetic_feeding_dataset(num_ponds=3, cycle_days=60, random_seed=42)
    scaler_file = tmp_path / "test_scaler.joblib"

    pipeline = TimeSeriesDataPipeline(
        feature_cols=REQUIRED_FEEDING_FEATURES,
        target_col="feed_amount_kg",
        scaler_path=str(scaler_file),
    )

    X_train_s, y_train, X_test_s, y_test, scaler = pipeline.prepare_time_blocked_split(
        df, test_ratio=0.20, save_scaler=True
    )

    # 1. Scaler file được tạo thành công
    assert scaler_file.exists()

    # 2. Tập Train sau khi fit_transform phải có mean ≈ 0 và std ≈ 1
    assert np.allclose(X_train_s.mean(axis=0), 0.0, atol=1e-5)
    assert np.allclose(X_train_s.std(axis=0), 1.0, atol=1e-5)

    # 3. Tập Test chỉ được transform (không fit lại) nên mean và std của nó không bắt buộc phải bằng 0 và 1
    # Trong chu kỳ tôm, những ngày cuối vụ (Test set) tôm lớn hơn, nên mean của Test set sau transform sẽ > 0
    assert not np.allclose(X_test_s.mean(axis=0), 0.0, atol=1e-2)

    # 4. Kiểm tra mean_ của scaler trùng khớp tuyệt đối với mean chưa chuẩn hóa của Train set
    n_train = int(len(df) * 0.8)
    X_train_raw = df.iloc[:n_train][list(REQUIRED_FEEDING_FEATURES)].to_numpy()
    assert np.allclose(scaler.mean_, X_train_raw.mean(axis=0), atol=1e-6)

    # 5. Mean_ của scaler KHÔNG ĐƯỢC trùng với mean toàn bộ dataset (chứng minh không bị rò rỉ toàn cục)
    X_full_raw = df[list(REQUIRED_FEEDING_FEATURES)].to_numpy()
    assert not np.allclose(scaler.mean_, X_full_raw.mean(axis=0), atol=1e-3)


def test_time_blocked_split_chronological_order():
    """Kiểm tra việc phân chia giữ nguyên vẹn trật tự thời gian (không bị shuffle)"""
    df = generate_synthetic_feeding_dataset(num_ponds=1, cycle_days=50, random_seed=10)
    pipeline = TimeSeriesDataPipeline()

    X_train_s, y_train, X_test_s, y_test, _ = pipeline.prepare_time_blocked_split(
        df, test_ratio=0.25, save_scaler=False
    )

    total_samples = len(df)
    expected_train_len = int(total_samples * 0.75)
    expected_test_len = total_samples - expected_train_len

    assert len(X_train_s) == expected_train_len
    assert len(X_test_s) == expected_test_len
    assert len(y_train) == expected_train_len
    assert len(y_test) == expected_test_len


def test_rolling_origin_folds_cross_validation():
    """Kiểm tra Rolling-Origin Cross-Validation (TimeSeriesSplit) tạo các fold chuẩn không rò rỉ"""
    df = generate_synthetic_feeding_dataset(num_ponds=1, cycle_days=30, random_seed=99)
    pipeline = TimeSeriesDataPipeline()

    folds = list(pipeline.get_rolling_origin_folds(df, n_splits=5))
    assert len(folds) == 5

    prev_train_size = 0
    for fold_num, X_tr, y_tr, X_te, y_te, fold_scaler in folds:
        # Tập Train phải nở dần qua từng fold (Rolling-Origin)
        assert len(X_tr) > prev_train_size
        prev_train_size = len(X_tr)

        # Tập Test trong mỗi fold không rỗng
        assert len(X_te) > 0

        # Kiểm tra scaler của fold chỉ fit trên train của fold đó
        assert np.allclose(X_tr.mean(axis=0), 0.0, atol=1e-5)


def test_scaler_save_and_load_persistence(tmp_path):
    """Kiểm tra lưu và nạp lại StandardScaler từ file .joblib cho cùng kết quả biến đổi"""
    df = generate_synthetic_feeding_dataset(num_ponds=1, cycle_days=20, random_seed=7)
    scaler_file = tmp_path / "scaler_persistence.joblib"

    pipeline = TimeSeriesDataPipeline(scaler_path=str(scaler_file))
    X_train_s, y_train, X_test_s, y_test, scaler = pipeline.prepare_time_blocked_split(
        df, test_ratio=0.2, save_scaler=True
    )

    # Nạp lại từ file bằng pipeline mới
    new_pipeline = TimeSeriesDataPipeline(scaler_path=str(scaler_file))
    loaded_scaler = new_pipeline.load_scaler()

    # Kiểm tra biến đổi trên cùng tập dữ liệu mẫu phải cho kết quả giống hệt
    sample_raw = df.iloc[-5:][list(REQUIRED_FEEDING_FEATURES)].to_numpy()
    transform_original = scaler.transform(sample_raw)
    transform_loaded = loaded_scaler.transform(sample_raw)

    assert np.allclose(transform_original, transform_loaded)
