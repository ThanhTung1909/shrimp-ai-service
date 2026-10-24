"""
AquaSense AI Microservice - FastAPI Main Application Entrypoint
Chạy độc lập trên Port 8000 (Resource Isolation Rule).
Phản hồi suy luận < 500ms nhờ Preloading Model vào RAM (Inference Latency Rule).
Do Backend-Integration-Agent chủ trì.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.models.xgboost_feeding import load_trained_feeding_model

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger("ai_service.main")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    FastAPI Lifespan Context Manager:
    Tải sẵn toàn bộ mô hình Machine Learning (.joblib) và Scaler vào RAM ngay khi ứng dụng khởi động.
    Đảm bảo thời gian phản hồi suy luận < 500ms (Inference Latency Rule).
    """
    logger.info("=" * 60)
    logger.info(f"Khởi động AquaSense AI Microservice trên môi trường: {settings.app_env}")
    logger.info(f"Cổng lắng nghe độc lập: {settings.app_port} (Resource Isolation Rule)")
    logger.info("=" * 60)

    # 1. Tải sẵn mô hình XGBoost Feeding Forecast & StandardScaler vào RAM
    try:
        model_path = "trained_models/xgboost_feeding_model.joblib"
        scaler_path = "trained_models/feeding_scaler.joblib"
        metadata_path = "trained_models/model_metadata.json"

        logger.info(f"[Lifespan Preload] Đang nạp mô hình XGBoost từ: {model_path}...")
        trainer = load_trained_feeding_model(
            model_path=model_path,
            scaler_path=scaler_path,
            metadata_path=metadata_path,
        )
        app.state.feeding_trainer = trainer

        # Đọc metadata nếu có
        meta_file = Path(metadata_path)
        if meta_file.exists():
            with open(meta_file, "r", encoding="utf-8") as f:
                app.state.model_metadata = json.load(f)
        else:
            app.state.model_metadata = {}

        logger.info(
            f"[Lifespan Preload] Nạp mô hình hoàn tất thành công. "
            f"Phiên bản: {app.state.model_metadata.get('version', '1.0.0')}, "
            f"Số đặc trưng: {len(trainer.feature_cols)}"
        )
    except Exception as e:
        logger.error(f"[Lifespan Preload Error] Không thể nạp mô hình vào RAM: {e}")
        app.state.feeding_trainer = None
        app.state.model_metadata = {}

    # 2. Khởi tạo Redis Cache Service bất đồng bộ
    from app.services.redis_cache import RedisCacheService
    redis_service = RedisCacheService()
    app.state.redis_service = redis_service
    is_redis_ready = await redis_service.ping()
    if is_redis_ready:
        logger.info("[Lifespan Redis] Kết nối Redis Cache Server thành công (TTL 1800s).")
    else:
        logger.warning("[Lifespan Redis Warning] Redis Server chưa sẵn sàng, kích hoạt chế độ Graceful Degradation.")

    yield

    # Dọn dẹp tài nguyên khi tắt service
    if hasattr(app.state, "redis_service") and app.state.redis_service is not None:
        await app.state.redis_service.close()
    logger.info("Dọn dẹp tài nguyên và tắt AquaSense AI Microservice.")


# Khởi tạo FastAPI App
app = FastAPI(
    title="AquaSense AI Microservice",
    description="Vi dịch vụ AI phân tích chất lượng nước, dự báo nhu cầu thức ăn và cảnh báo rủi ro cho ao tôm thông minh.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Cấu hình CORS Middleware
# Cho phép Core Backend NestJS (port 3000), Web Portal (port 3001) và Mobile App kết nối
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "*",  # Cho phép mọi nguồn trong môi trường dev / local network
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==============================================================================
# Global Exception Handlers
# ==============================================================================

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Bắt và chuẩn hóa lỗi dữ liệu đầu vào không hợp lệ từ client (HTTP 422)"""
    errors = []
    for err in exc.errors():
        loc = " -> ".join([str(x) for x in err.get("loc", [])])
        msg = err.get("msg", "Dữ liệu không hợp lệ")
        errors.append({"field": loc, "message": msg, "type": err.get("type")})

    logger.warning(f"[Validation Error] {request.method} {request.url.path} - {errors}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "status": "error",
            "error_type": "VALIDATION_ERROR",
            "message": "Dữ liệu yêu cầu không đúng định dạng hoặc vi phạm quy tắc sinh học.",
            "errors": errors,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    """Bắt và chuẩn hóa lỗi vi phạm giá trị nghiệp vụ (HTTP 400)"""
    logger.warning(f"[Value Error] {request.method} {request.url.path} - {str(exc)}")
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "status": "error",
            "error_type": "BAD_REQUEST",
            "message": str(exc),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Chuẩn hóa lỗi HTTPException"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error",
            "error_type": "HTTP_EXCEPTION",
            "message": exc.detail,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Bắt các lỗi ngoại lệ chưa được xử lý (HTTP 500)"""
    logger.error(f"[Internal Server Error] {request.method} {request.url.path} - {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "status": "error",
            "error_type": "INTERNAL_SERVER_ERROR",
            "message": "Đã xảy ra lỗi nội bộ máy chủ trong quá trình xử lý AI.",
            "detail": str(exc),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


# ==============================================================================
# Base Endpoints (Root & Health Check)
# ==============================================================================

@app.get("/", tags=["General"])
async def root():
    """Thông tin chào mừng và giới thiệu dịch vụ AI"""
    return {
        "service": "AquaSense AI Microservice",
        "description": "Vi dịch vụ AI dự báo lượng thức ăn, phân tích chất lượng nước và cảnh báo sớm ao tôm.",
        "version": "1.0.0",
        "port": settings.app_port,
        "docs_url": "/docs",
        "health_check": "/health",
    }


@app.get("/health", tags=["General"])
async def health_check():
    """
    Kiểm tra trạng thái sức khỏe của AI Service:
    - RAM Model Preload status
    - TimescaleDB connectivity
    - Cổng và môi trường
    """
    from app.database import check_db_connection

    is_model_loaded = hasattr(app.state, "feeding_trainer") and app.state.feeding_trainer is not None
    model_version = getattr(app.state, "model_metadata", {}).get("version", "1.0.0") if is_model_loaded else None

    # Kiểm tra database nhanh (không block nếu offline)
    db_status = check_db_connection()

    # Kiểm tra Redis nhanh
    redis_connected = False
    if hasattr(app.state, "redis_service") and app.state.redis_service is not None:
        redis_connected = await app.state.redis_service.ping()

    return {
        "status": "ok" if is_model_loaded else "degraded",
        "service": "AquaSense AI Microservice",
        "environment": settings.app_env,
        "port": settings.app_port,
        "model_loaded": is_model_loaded,
        "model_version": model_version,
        "database": db_status,
        "redis": {"connected": redis_connected},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ==============================================================================
# Include Routers (API Endpoints)
# ==============================================================================

from app.api.v1.router import api_v1_router
from app.api.v1.predictions import router as predictions_direct_router

# Đăng ký API v1 chuẩn: /api/v1/...
app.include_router(api_v1_router, prefix="/api/v1")

# Đăng ký trực tiếp cho NestJS PredictionsService: /api/predict
app.include_router(predictions_direct_router, prefix="/api")

