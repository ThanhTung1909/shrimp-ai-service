"""
Unit tests cho TASK-BE-01: FastAPI Lifespan preloading, CORS, và Global Exception Handlers.
Do Backend-Integration-Agent chủ trì.
"""

import pytest
from fastapi import APIRouter, HTTPException
from fastapi.testclient import TestClient

from app.api.deps import get_app_settings, get_feeding_trainer
from app.main import app

# Router phụ phục vụ kiểm thử Exception Handlers
dummy_router = APIRouter(prefix="/test-exceptions")


@dummy_router.get("/trigger-value-error")
async def trigger_value_error():
    raise ValueError("Lỗi nghiệp vụ kiểm thử: Dữ liệu bị vi phạm!")


@dummy_router.get("/trigger-internal-error")
async def trigger_internal_error():
    raise RuntimeError("Lỗi hệ thống bất ngờ ngoài ý muốn!")


@dummy_router.get("/trigger-http-error")
async def trigger_http_error():
    raise HTTPException(status_code=403, detail="Không có quyền truy cập tài nguyên này.")


# Đăng ký tạm thời router kiểm thử
app.include_router(dummy_router)


@pytest.fixture(scope="module")
def client():
    """Khởi tạo TestClient kích hoạt toàn diện Lifespan context manager"""
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_lifespan_preloads_model_into_app_state(client):
    """
    Kiểm tra FastAPI Lifespan đã nạp sẵn mô hình XGBoost và metadata vào RAM (Inference Latency Rule)
    """
    assert hasattr(app.state, "feeding_trainer"), "app.state thiếu thuộc tính feeding_trainer"
    assert app.state.feeding_trainer is not None, "feeding_trainer chưa được nạp"
    assert hasattr(app.state, "model_metadata"), "app.state thiếu model_metadata"

    # Kiểm tra trainer đã sẵn sàng suy luận với 7 biến thực nghiệm
    assert len(app.state.feeding_trainer.feature_cols) == 7

    # Dự báo thử nghiệm ngay từ RAM
    sample = [45, 14.5, 4.2, 0.05, 0.0, 25.0, 0.0]
    preds = app.state.feeding_trainer.predict(sample, is_scaled=False)
    assert preds[0] > 0.0


def test_root_endpoint(client):
    """Kiểm tra GET / trả về thông tin chào mừng dịch vụ và cổng 8000"""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()

    assert data["service"] == "AquaSense AI Microservice"
    assert data["version"] == "1.0.0"
    assert data["port"] == 8000
    assert data["docs_url"] == "/docs"
    assert data["health_check"] == "/health"


def test_health_check_endpoint(client):
    """Kiểm tra GET /health trả về trạng thái dịch vụ và model đã nạp"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()

    assert data["status"] in ["ok", "degraded"]
    assert data["service"] == "AquaSense AI Microservice"
    assert data["model_loaded"] is True
    assert data["model_version"] == "1.0.0"
    assert "database" in data
    assert "timestamp" in data


def test_cors_headers_present(client):
    """Kiểm tra CORS headers cho phép gọi từ Web Portal hoặc Core Backend"""
    origin = "http://localhost:3000"
    response = client.options(
        "/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    # FastApi CORSMiddleware xử lý OPTIONS request preflight
    assert response.headers.get("access-control-allow-origin") in ["*", origin]


def test_value_error_exception_handler(client):
    """Kiểm tra Global Exception Handler bắt ValueError và trả về 400 chuẩn JSON"""
    response = client.get("/test-exceptions/trigger-value-error")
    assert response.status_code == 400
    data = response.json()

    assert data["status"] == "error"
    assert data["error_type"] == "BAD_REQUEST"
    assert "Lỗi nghiệp vụ kiểm thử" in data["message"]
    assert "timestamp" in data


def test_http_exception_handler(client):
    """Kiểm tra xử lý HTTPException chuẩn hóa"""
    response = client.get("/test-exceptions/trigger-http-error")
    assert response.status_code == 403
    data = response.json()

    assert data["status"] == "error"
    assert data["error_type"] == "HTTP_EXCEPTION"
    assert "Không có quyền" in data["message"]


def test_internal_server_error_handler(client):
    """Kiểm tra Global Exception Handler bắt Exception không mong muốn và trả về 500 chuẩn JSON"""
    response = client.get("/test-exceptions/trigger-internal-error")
    assert response.status_code == 500
    data = response.json()

    assert data["status"] == "error"
    assert data["error_type"] == "INTERNAL_SERVER_ERROR"
    assert "Đã xảy ra lỗi nội bộ máy chủ" in data["message"]


def test_dependency_injection(client):
    """Kiểm tra các dependencies get_feeding_trainer và get_app_settings"""
    settings = get_app_settings()
    assert settings.app_port == 8000

    # Giả lập một Request để test get_feeding_trainer
    class MockRequest:
        class MockApp:
            state = app.state
        app = MockApp()

    trainer = get_feeding_trainer(MockRequest())
    assert trainer is not None
    assert trainer == app.state.feeding_trainer
