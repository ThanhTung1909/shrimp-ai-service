"""
Test suite cho TASK-DP-01: Kết nối TimescaleDB và truy vấn time_bucket
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest
from app.config import Settings, get_settings
from app.database import check_db_connection
from app.services.pipeline import (
    SQL_TELEMETRY_TIME_BUCKET,
    fetch_telemetry_time_bucket,
    fetch_latest_pond_telemetry,
)


def test_settings_database_urls():
    """Kiểm tra cấu hình Settings tạo đúng Database URLs cho PostgreSQL/TimescaleDB"""
    settings = Settings(
        DB_HOST="localhost",
        DB_PORT=5432,
        DB_USER="postgres",
        DB_PASS="LocalSecretPass!23",
        DB_NAME="shrimp_local_db",
    )
    assert settings.sync_database_url == "postgresql://postgres:LocalSecretPass!23@localhost:5432/shrimp_local_db"
    assert settings.async_database_url == "postgresql+asyncpg://postgres:LocalSecretPass!23@localhost:5432/shrimp_local_db"


def test_sql_query_contains_required_columns_and_time_bucket():
    """Kiểm tra câu lệnh SQL truy xuất đúng hàm time_bucket và 5 thông số quan trọng"""
    sql = SQL_TELEMETRY_TIME_BUCKET.lower()
    assert "time_bucket(:bucket_interval, td.recorded_at)" in sql
    assert "avg(td.temperature)" in sql
    assert "avg(td.ph)" in sql
    assert "avg(td.salinity)" in sql
    assert "avg(td.dissolved_oxygen)" in sql
    assert "avg(td.turbidity)" in sql
    assert "join device d on td.device_id = d.device_id" in sql
    assert "where d.pond_id = :pond_id" in sql


def test_fetch_telemetry_time_bucket_with_mock_session():
    """Kiểm tra hàm fetch_telemetry_time_bucket xử lý dữ liệu và tạo DataFrame chuẩn"""
    mock_session = MagicMock()
    mock_result = MagicMock()
    
    mock_result.keys.return_value = [
        "bucket_time", "pond_id", "avg_temperature", "avg_ph",
        "avg_salinity", "avg_dissolved_oxygen", "min_dissolved_oxygen",
        "max_dissolved_oxygen", "avg_turbidity", "avg_water_level", "sample_count"
    ]
    
    sample_time = datetime(2026, 9, 4, 8, 0, 0, tzinfo=timezone.utc)
    mock_result.fetchall.return_value = [
        (sample_time, "pond-uuid-1", 28.5, 7.8, 15.2, 5.8, 5.6, 6.0, 22.0, 1.25, 4)
    ]
    mock_session.execute.return_value = mock_result

    start_time = datetime(2026, 9, 4, 0, 0, 0, tzinfo=timezone.utc)
    end_time = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)

    df = fetch_telemetry_time_bucket(
        pond_id="pond-uuid-1",
        start_time=start_time,
        end_time=end_time,
        bucket_interval="15 minutes",
        session=mock_session,
    )

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 1
    assert df.index.name == "bucket_time"
    assert "avg_temperature" in df.columns
    assert df.iloc[0]["avg_temperature"] == 28.5
    assert df.iloc[0]["avg_dissolved_oxygen"] == 5.8


def test_fetch_telemetry_time_bucket_empty():
    """Kiểm tra xử lý khi không có dữ liệu trả về DataFrame rỗng"""
    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.keys.return_value = ["bucket_time", "pond_id", "avg_temperature"]
    mock_result.fetchall.return_value = []
    mock_session.execute.return_value = mock_result

    df = fetch_telemetry_time_bucket(
        pond_id="empty-pond",
        start_time=datetime(2026, 9, 4, 0, 0, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 9, 4, 1, 0, 0, tzinfo=timezone.utc),
        session=mock_session,
    )

    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_check_db_connection_offline_handling():
    """Kiểm tra hàm check_db_connection bắt lỗi mềm khi chưa có database connection"""
    with patch("app.database.get_engine") as mock_get_engine:
        mock_get_engine.side_effect = Exception("Connection refused")
        status = check_db_connection()
        assert status["connected"] is False
        assert "Connection refused" in status["error"]
