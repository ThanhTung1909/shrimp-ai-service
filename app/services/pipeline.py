"""
AquaSense AI Data Pipeline Service
Phụ trách trích xuất, làm sạch và chuẩn bị dữ liệu chuỗi thời gian từ TimescaleDB.
Do Data-Pipeline-Agent chủ trì.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Union
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.database import SessionLocal, get_engine

logger = logging.getLogger("ai_service.pipeline")

# ==============================================================================
# TASK-DP-01: Truy Vấn Chuỗi Thời Gian Telemetry Theo Time-Bucket & Pond ID
# ==============================================================================

SQL_TELEMETRY_TIME_BUCKET = """
SELECT 
    time_bucket(:bucket_interval, td.recorded_at) AS bucket_time,
    d.pond_id,
    AVG(td.temperature) AS avg_temperature,
    AVG(td.ph) AS avg_ph,
    AVG(td.salinity) AS avg_salinity,
    AVG(td.dissolved_oxygen) AS avg_dissolved_oxygen,
    MIN(td.dissolved_oxygen) AS min_dissolved_oxygen,
    MAX(td.dissolved_oxygen) AS max_dissolved_oxygen,
    AVG(td.turbidity) AS avg_turbidity,
    AVG(td.water_level) AS avg_water_level,
    COUNT(td.id) AS sample_count
FROM telemetry_data td
JOIN device d ON td.device_id = d.device_id
WHERE d.pond_id = :pond_id
  AND td.recorded_at >= :start_time
  AND td.recorded_at <= :end_time
GROUP BY bucket_time, d.pond_id
ORDER BY bucket_time ASC;
"""

SQL_LATEST_POND_TELEMETRY = """
SELECT 
    td.recorded_at,
    d.pond_id,
    td.temperature,
    td.ph,
    td.salinity,
    td.dissolved_oxygen,
    td.turbidity,
    td.water_level
FROM telemetry_data td
JOIN device d ON td.device_id = d.device_id
WHERE d.pond_id = :pond_id
ORDER BY td.recorded_at DESC
LIMIT :limit;
"""


def fetch_telemetry_time_bucket(
    pond_id: str,
    start_time: datetime,
    end_time: datetime,
    bucket_interval: str = "15 minutes",
    session: Optional[Session] = None,
) -> pd.DataFrame:
    """
    Truy xuất chuỗi thời gian telemetry được gom cụm theo time_bucket của TimescaleDB.
    
    Args:
        pond_id: UUID của ao nuôi cần truy xuất dữ liệu.
        start_time: Mốc thời gian bắt đầu.
        end_time: Mốc thời gian kết thúc.
        bucket_interval: Khoảng gom cụm của TimescaleDB (mặc định: '15 minutes').
        session: SQLAlchemy Session tùy chọn. Nếu None, tự tạo session và đóng sau khi truy vấn.
        
    Returns:
        pd.DataFrame chứa chuỗi thời gian đã gom cụm với index là 'bucket_time'.
    """
    logger.info(
        f"[fetch_telemetry_time_bucket] Pond={pond_id}, "
        f"Window=[{start_time.isoformat()} -> {end_time.isoformat()}], Bucket={bucket_interval}"
    )

    close_session_after = False
    if session is None:
        session = SessionLocal()
        close_session_after = True

    try:
        params = {
            "pond_id": pond_id,
            "start_time": start_time,
            "end_time": end_time,
            "bucket_interval": bucket_interval,
        }
        result = session.execute(text(SQL_TELEMETRY_TIME_BUCKET), params)
        rows = result.fetchall()
        columns = list(result.keys())

        if not rows:
            logger.warning(f"Không có dữ liệu telemetry cho ao {pond_id} trong khoảng thời gian chỉ định.")
            return pd.DataFrame(columns=columns)

        df = pd.DataFrame(rows, columns=columns)
        df["bucket_time"] = pd.to_datetime(df["bucket_time"], utc=True)
        df.set_index("bucket_time", inplace=True)
        return df

    except Exception as e:
        logger.error(f"[fetch_telemetry_time_bucket Error] {e}")
        raise e
    finally:
        if close_session_after:
            session.close()


def fetch_latest_pond_telemetry(
    pond_id: str,
    limit: int = 10,
    session: Optional[Session] = None,
) -> pd.DataFrame:
    """
    Truy xuất N bản ghi telemetry mới nhất của một ao nuôi (không qua time_bucket).
    """
    close_session_after = False
    if session is None:
        session = SessionLocal()
        close_session_after = True

    try:
        params = {"pond_id": pond_id, "limit": limit}
        result = session.execute(text(SQL_LATEST_POND_TELEMETRY), params)
        rows = result.fetchall()
        columns = list(result.keys())

        if not rows:
            return pd.DataFrame(columns=columns)

        df = pd.DataFrame(rows, columns=columns)
        df["recorded_at"] = pd.to_datetime(df["recorded_at"], utc=True)
        return df
    finally:
        if close_session_after:
            session.close()


# ==============================================================================
# TASK-DP-02: Làm Sạch Dữ Liệu & Nội Suy Tuyến Tính (Linear Interpolation)
# ==============================================================================

BIOLOGICAL_LIMITS = {
    "temperature": (15.0, 42.0),
    "avg_temperature": (15.0, 42.0),
    "ph": (5.5, 10.0),
    "avg_ph": (5.5, 10.0),
    "salinity": (0.0, 45.0),
    "avg_salinity": (0.0, 45.0),
    "dissolved_oxygen": (0.0, 15.0),
    "avg_dissolved_oxygen": (0.0, 15.0),
    "min_dissolved_oxygen": (0.0, 15.0),
    "max_dissolved_oxygen": (0.0, 15.0),
    "turbidity": (0.0, 200.0),
    "avg_turbidity": (0.0, 200.0),
    "water_level": (0.0, 5.0),
    "avg_water_level": (0.0, 5.0),
}


def filter_biological_outliers(
    df: pd.DataFrame,
    limits: Optional[dict] = None,
    replace_with_nan: bool = True,
) -> pd.DataFrame:
    """
    Phát hiện và lọc các giá trị đo cảm biến nằm ngoài biên sinh học an toàn ao tôm.
    
    Args:
        df: DataFrame chứa chuỗi dữ liệu telemetry.
        limits: Từ điển biên (min, max) cho từng metric. Mặc định dùng BIOLOGICAL_LIMITS.
        replace_with_nan: Nếu True, chuyển outlier thành NaN để chuẩn bị cho bước nội suy.
        
    Returns:
        DataFrame đã lọc nhiễu.
    """
    if df.empty:
        return df.copy()

    df_cleaned = df.copy()
    thresholds = limits or BIOLOGICAL_LIMITS

    outlier_counts = {}
    for column, (min_val, max_val) in thresholds.items():
        if column in df_cleaned.columns:
            is_numeric = pd.to_numeric(df_cleaned[column], errors="coerce")
            invalid_mask = (is_numeric < min_val) | (is_numeric > max_val)
            count = int(invalid_mask.sum())
            if count > 0:
                outlier_counts[column] = count
                if replace_with_nan:
                    df_cleaned.loc[invalid_mask, column] = float("nan")
                else:
                    df_cleaned[column] = is_numeric.clip(lower=min_val, upper=max_val)

    if outlier_counts:
        logger.info(f"[filter_biological_outliers] Đã phát hiện và lọc ngoại lai: {outlier_counts}")

    return df_cleaned


def clean_and_interpolate_telemetry(
    df: pd.DataFrame,
    freq: str = "15min",
    max_gap_hours: float = 2.0,
    time_col: Optional[str] = None,
) -> pd.DataFrame:
    """
    Quy trình chuẩn hóa chuỗi thời gian telemetry:
    1. Đảm bảo Index là DatetimeIndex chuẩn có bước nhảy freq đồng đều.
    2. Lọc các giá trị ngoại lai sinh học thành NaN.
    3. Nội suy tuyến tính (Linear Interpolation) cho các khoảng rớt mạng IoT (<= max_gap_hours).
    4. Cắm cờ cảnh báo nếu khoảng khuyết vượt quá ngưỡng trôi dạt max_gap_hours.
    
    Args:
        df: DataFrame đầu vào.
        freq: Tần suất đồng bộ chuỗi thời gian (mặc định: '15min').
        max_gap_hours: Giới hạn tối đa cho phép nội suy (mặc định: 2.0 giờ).
        time_col: Tên cột thời gian nếu chưa set index.
        
    Returns:
        pd.DataFrame sạch, đầy đủ chỉ số, có cờ theo dõi nội suy.
    """
    if df.empty:
        return df.copy()

    df_proc = df.copy()

    # 1. Đảm bảo DatetimeIndex
    if time_col and time_col in df_proc.columns:
        df_proc[time_col] = pd.to_datetime(df_proc[time_col], utc=True)
        df_proc.set_index(time_col, inplace=True)
    elif not isinstance(df_proc.index, pd.DatetimeIndex):
        try:
            df_proc.index = pd.to_datetime(df_proc.index, utc=True)
        except Exception as e:
            logger.error(f"[clean_and_interpolate_telemetry] Index không thể chuyển thành DatetimeIndex: {e}")
            raise ValueError(f"DataFrame index phải là DatetimeIndex: {e}")

    df_proc.sort_index(inplace=True)

    # 2. Lọc ngoại lai sinh học
    df_proc = filter_biological_outliers(df_proc, replace_with_nan=True)

    # 3. Đồng bộ lưới thời gian (Reindex/Resample đều đặn)
    full_idx = pd.date_range(start=df_proc.index.min(), end=df_proc.index.max(), freq=freq)
    df_reindexed = df_proc.reindex(full_idx)

    # Giữ lại pond_id nếu có
    if "pond_id" in df_proc.columns:
        first_valid_pond = df_proc["pond_id"].dropna().iloc[0] if not df_proc["pond_id"].dropna().empty else None
        if first_valid_pond:
            df_reindexed["pond_id"] = df_reindexed["pond_id"].fillna(first_valid_pond)

    # 4. Tính toán limit steps cho nội suy tuyến tính
    # Với freq 15min -> 1 giờ = 4 bước -> 2 giờ = 8 bước
    freq_delta = pd.Timedelta(freq)
    steps_per_hour = pd.Timedelta(hours=1) / freq_delta
    limit_steps = max(1, int(round(steps_per_hour * max_gap_hours)))

    numeric_cols = df_reindexed.select_dtypes(include=["number"]).columns.tolist()

    # Đánh dấu những điểm dữ liệu vốn bị khuyết
    original_nan_mask = df_reindexed[numeric_cols].isna()

    # 5. Nội suy tuyến tính với giới hạn limit_steps
    df_interpolated = df_reindexed.copy()
    df_interpolated[numeric_cols] = df_reindexed[numeric_cols].interpolate(
        method="linear",
        limit=limit_steps,
        limit_direction="forward",
    )

    # 6. Đánh dấu cờ chất lượng dữ liệu
    # is_interpolated: True tại các điểm được bù đắp dữ liệu bằng nội suy
    interpolated_mask = original_nan_mask & (~df_interpolated[numeric_cols].isna())
    df_interpolated["is_interpolated"] = interpolated_mask.any(axis=1)

    # gap_exceeded_limit: True nếu sau khi nội suy mà vẫn còn NaN (khoảng mất tín hiệu > 2h)
    remaining_nan = df_interpolated[numeric_cols].isna().any(axis=1)
    df_interpolated["gap_exceeded_limit"] = remaining_nan

    logger.info(
        f"[clean_and_interpolate_telemetry] Tổng mẫu: {len(df_interpolated)}, "
        f"Số điểm nội suy: {int(df_interpolated['is_interpolated'].sum())}, "
        f"Số điểm vượt ngưỡng khuyết {max_gap_hours}h: {int(df_interpolated['gap_exceeded_limit'].sum())}"
    )

    return df_interpolated
