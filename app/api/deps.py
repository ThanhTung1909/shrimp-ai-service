"""
FastAPI Dependencies cho AquaSense AI Microservice.
Do Backend-Integration-Agent quản lý.
"""

from typing import Generator
from fastapi import Request
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models.xgboost_feeding import XGBoostFeedingTrainer


def get_app_settings() -> Settings:
    """Dependency cung cấp cài đặt toàn cục"""
    return get_settings()


def get_feeding_trainer(request: Request) -> XGBoostFeedingTrainer:
    """
    Dependency lấy XGBoost Feeding Trainer đã nạp sẵn trong RAM qua FastAPI lifespan.
    Đảm bảo thời gian phản hồi suy luận < 500ms.
    """
    trainer: XGBoostFeedingTrainer = getattr(request.app.state, "feeding_trainer", None)
    if trainer is None:
        from app.models.xgboost_feeding import load_trained_feeding_model
        trainer = load_trained_feeding_model()
        request.app.state.feeding_trainer = trainer
    return trainer


def get_database_session() -> Generator[Session, None, None]:
    """Dependency cung cấp phiên làm việc CSDL TimescaleDB/PostgreSQL"""
    yield from get_db()


def get_redis_cache(request: Request):
    """Dependency cung cấp Redis Cache Service từ app.state"""
    redis_svc = getattr(request.app.state, "redis_service", None)
    if redis_svc is None:
        from app.services.redis_cache import RedisCacheService
        redis_svc = RedisCacheService()
        request.app.state.redis_service = redis_svc
    return redis_svc

