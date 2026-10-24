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
