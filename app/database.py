import asyncio
import logging
from typing import Generator, Optional
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.config import get_settings

logger = logging.getLogger("ai_service.database")

settings = get_settings()

Base = declarative_base()

_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def get_engine() -> Engine:
    """
    Trả về hoặc khởi tạo SQLAlchemy Engine cho TimescaleDB/PostgreSQL.
    Sử dụng lazy initialization để tránh crash khi chưa cài đặt driver trên môi trường dev.
    """
    global _engine
    if _engine is None:
        try:
            _engine = create_engine(
                settings.sync_database_url,
                pool_size=10,
                max_overflow=20,
                pool_pre_ping=True,
                pool_recycle=3600,
                connect_args={"connect_timeout": settings.db_connect_timeout_seconds},
            )
        except Exception as e:
            logger.warning(
                f"[Database Engine Warning] Chưa thể khởi tạo kết nối database trực tiếp ({e}). "
                "Đang chạy ở chế độ offline/mock."
            )
            raise e
    return _engine


def get_sessionmaker() -> sessionmaker:
    """Trả về Sessionmaker gắn với engine hiện tại"""
    global _SessionLocal
    if _SessionLocal is None:
        eng = get_engine()
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=eng)
    return _SessionLocal


def SessionLocal() -> Session:
    """Helper gọi sessionmaker tương thích ngược"""
    sm = get_sessionmaker()
    return sm()


def get_db() -> Generator[Session, None, None]:
    """Dependency cung cấp Session CSDL cho API endpoints hoặc worker"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _database_status(error: Optional[str] = None) -> dict:
    return {
        "connected": False,
        "timescaledb_installed": False,
        "timescaledb_version": None,
        "error": error,
    }


def check_db_connection() -> dict:
    """
    Kiểm tra trạng thái kết nối tới cơ sở dữ liệu TimescaleDB.
    Xác minh extension TimescaleDB đã sẵn sàng.
    """
    status = _database_status()
    try:
        eng = get_engine()
        # SET LOCAL is scoped to this read-only probe transaction, so a slow
        # database query cannot leave a persistent statement timeout in the pool.
        with eng.begin() as connection:
            statement_timeout_ms = max(1, int(settings.db_health_check_timeout_seconds * 1000))
            connection.execute(text(f"SET LOCAL statement_timeout = {statement_timeout_ms}"))
            # 1. Kiểm tra kết nối cơ bản
            result = connection.execute(text("SELECT 1;")).scalar()
            if result == 1:
                status["connected"] = True

            # 2. Kiểm tra extension TimescaleDB
            ext_result = connection.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb';")
            ).fetchone()

            if ext_result:
                status["timescaledb_installed"] = True
                status["timescaledb_version"] = ext_result[0]

        logger.info(
            f"[TimescaleDB Check] Connected: {status['connected']}, "
            f"TimescaleDB Version: {status['timescaledb_version']}"
        )
    except Exception as e:
        status["error"] = str(e)
        logger.warning(f"[TimescaleDB Connection Error] {e}")

    return status


async def check_db_connection_async() -> dict:
    """Run the synchronous SQLAlchemy health probe off the FastAPI event loop."""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(check_db_connection),
            timeout=settings.db_health_check_timeout_seconds,
        )
    except asyncio.TimeoutError:
        timeout = settings.db_health_check_timeout_seconds
        logger.warning("[TimescaleDB Connection Timeout] Health probe exceeded %.2fs", timeout)
        return _database_status(f"database health check timed out after {timeout:.2f} seconds")
