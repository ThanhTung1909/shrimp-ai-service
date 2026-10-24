"""
Test suite cho TASK-DP-02: Làm sạch dữ liệu và nội suy tuyến tính (Linear Interpolation)
"""

from datetime import datetime, timezone
import numpy as np
import pandas as pd
import pytest
from app.services.pipeline import (
    BIOLOGICAL_LIMITS,
    filter_biological_outliers,
    clean_and_interpolate_telemetry,
)


def test_filter_biological_outliers_identifies_anomalies():
    """Kiểm tra hàm lọc ngoại lai sinh học phát hiện đúng các điểm vượt ngưỡng vô lý"""
    dates = pd.date_range("2026-09-04 08:00:00", periods=5, freq="15min", tz="UTC")
    df = pd.DataFrame(
        {
            "avg_temperature": [28.5, 99.0, 29.0, -10.0, 28.8], # 99 và -10 là vô lý
            "avg_ph": [7.5, 14.5, 7.8, 2.0, 7.6],                 # 14.5 và 2.0 là vô lý
            "avg_dissolved_oxygen": [5.5, -1.0, 5.2, 25.0, 5.0],  # -1.0 và 25.0 là vô lý
            "avg_salinity": [15.0, 15.2, 80.0, 15.1, 15.0],      # 80.0 là vô lý
        },
        index=dates,
    )

    cleaned = filter_biological_outliers(df, replace_with_nan=True)

    # Các giá trị hợp lệ giữ nguyên
    assert cleaned.loc[dates[0], "avg_temperature"] == 28.5
    assert cleaned.loc[dates[2], "avg_temperature"] == 29.0

    # Các ngoại lai bị biến thành NaN
    assert np.isnan(cleaned.loc[dates[1], "avg_temperature"])
    assert np.isnan(cleaned.loc[dates[3], "avg_temperature"])
    assert np.isnan(cleaned.loc[dates[1], "avg_ph"])
    assert np.isnan(cleaned.loc[dates[3], "avg_ph"])
    assert np.isnan(cleaned.loc[dates[1], "avg_dissolved_oxygen"])
    assert np.isnan(cleaned.loc[dates[3], "avg_dissolved_oxygen"])
    assert np.isnan(cleaned.loc[dates[2], "avg_salinity"])


def test_clean_and_interpolate_short_gap_under_2_hours():
    """Kiểm tra rớt mạng ngắn (<= 2 tiếng) được nội suy tuyến tính chính xác và gắn cờ is_interpolated"""
    # 5 mốc thời gian: 00:00, 00:15, 00:30, 00:45, 01:00
    # Khuyết 2 mốc ở giữa: 00:15 và 00:30 (30 phút khuyết < 2 giờ)
    dates = pd.date_range("2026-09-04 00:00:00", periods=5, freq="15min", tz="UTC")
    df_raw = pd.DataFrame(
        {
            "pond_id": ["pond-01"] * 5,
            "avg_temperature": [28.0, np.nan, np.nan, 29.5, 30.0],
            "avg_dissolved_oxygen": [6.0, np.nan, np.nan, 5.1, 5.0],
        },
        index=dates,
    )

    cleaned = clean_and_interpolate_telemetry(df_raw, freq="15min", max_gap_hours=2.0)

    # 1. Toàn bộ mốc bị khuyết đều được điền đầy đủ
    assert not cleaned["avg_temperature"].isna().any()
    assert not cleaned["avg_dissolved_oxygen"].isna().any()

    # 2. Giá trị nội suy tuyến tính: 28.0 -> (step=0.5) -> 28.5 -> 29.0 -> 29.5
    assert pytest.approx(cleaned.loc[dates[1], "avg_temperature"], 0.01) == 28.5
    assert pytest.approx(cleaned.loc[dates[2], "avg_temperature"], 0.01) == 29.0

    # 3. Cờ is_interpolated được bật đúng tại các điểm được nội suy
    assert cleaned.loc[dates[0], "is_interpolated"] == False
    assert cleaned.loc[dates[1], "is_interpolated"] == True
    assert cleaned.loc[dates[2], "is_interpolated"] == True
    assert cleaned.loc[dates[3], "is_interpolated"] == False

    # 4. Cờ gap_exceeded_limit là False vì không vượt quá 2h
    assert cleaned["gap_exceeded_limit"].sum() == 0


def test_clean_and_interpolate_long_gap_exceeds_2_hours():
    """Kiểm tra mất tín hiệu kéo dài (> 2 tiếng): dừng nội suy sau 8 bước (2h) và cắm cờ gap_exceeded_limit"""
    # 16 mốc thời gian (4 giờ liên tục)
    # Khuyết từ index 1 đến 14 (14 bước = 3.5 giờ khuyết > 2 giờ)
    dates = pd.date_range("2026-09-04 00:00:00", periods=16, freq="15min", tz="UTC")
    temp_vals = [28.0] + [np.nan] * 14 + [31.0]

    df_raw = pd.DataFrame(
        {
            "pond_id": ["pond-01"] * 16,
            "avg_temperature": temp_vals,
        },
        index=dates,
    )

    cleaned = clean_and_interpolate_telemetry(df_raw, freq="15min", max_gap_hours=2.0)

    # Với limit_steps = 8 (2 giờ):
    # dates[1] đến dates[8] được nội suy
    # dates[9] đến dates[14] KHÔNG được nội suy tiếp và vẫn là NaN
    assert not np.isnan(cleaned.loc[dates[8], "avg_temperature"])
    assert np.isnan(cleaned.loc[dates[9], "avg_temperature"])
    assert np.isnan(cleaned.loc[dates[14], "avg_temperature"])

    # Cờ gap_exceeded_limit phải True tại các điểm còn lại
    assert cleaned.loc[dates[9], "gap_exceeded_limit"] == True
    assert cleaned.loc[dates[14], "gap_exceeded_limit"] == True


def test_clean_and_interpolate_empty_and_irregular_grid():
    """Kiểm tra xử lý DataFrame rỗng hoặc chuỗi thời gian bị nhảy cóc mốc"""
    # 1. Empty DF
    empty_df = pd.DataFrame()
    assert clean_and_interpolate_telemetry(empty_df).empty

    # 2. Dữ liệu bị thiếu hẳn timestamp trong bảng (không có dòng nào trong DB)
    # Ví dụ chỉ có dòng lúc 00:00 và 00:45 (bị thiếu hẳn dòng 00:15 và 00:30)
    sparse_dates = [
        pd.Timestamp("2026-09-04 00:00:00", tz="UTC"),
        pd.Timestamp("2026-09-04 00:45:00", tz="UTC"),
    ]
    df_sparse = pd.DataFrame(
        {"avg_temperature": [28.0, 29.5]},
        index=sparse_dates,
    )

    cleaned = clean_and_interpolate_telemetry(df_sparse, freq="15min", max_gap_hours=2.0)

    # Grid được tái tạo đầy đủ 4 điểm: 00:00, 00:15, 00:30, 00:45
    assert len(cleaned) == 4
    assert pytest.approx(cleaned.iloc[1]["avg_temperature"], 0.01) == 28.5
    assert pytest.approx(cleaned.iloc[2]["avg_temperature"], 0.01) == 29.0
    assert cleaned.iloc[1]["is_interpolated"] == True
