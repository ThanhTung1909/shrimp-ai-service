"""
Unit tests cho TASK-BE-05: RabbitMQ Event-Driven Message Publisher.
Kiểm tra chi tiết:
- Định dạng sự kiện ai.risk.detected
- Khai báo Topic Exchange shrimp.events và Queue ai_risk_alerts
- Cơ chế chịu lỗi (Graceful degradation) khi RabbitMQ broker offline
- Tự động đẩy sự kiện khi API phát hiện nguy cơ cao (Feeding rủi ro cao, Nước nguy cấp)
- Báo cáo trạng thái RabbitMQ trong GET /health
Do Backend-Integration-Agent chủ trì.
"""

import asyncio
import json
import time
from typing import Any, Dict, List, Optional
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.rabbitmq_publisher import (
    DEFAULT_EXCHANGE,
    DEFAULT_QUEUE,
    ROUTING_KEY_RISK_DETECTED,
    RabbitMQPublisher,
)


class MockExchange:
    """Mock AMQP Exchange để ghi nhận các message đã xuất bản trong unit tests"""

    def __init__(self):
        self.published_messages: List[Dict[str, Any]] = []

    async def publish(self, message: Any, routing_key: str):
        payload = json.loads(message.body.decode("utf-8"))
        self.published_messages.append({
            "routing_key": routing_key,
            "payload": payload,
            "content_type": message.content_type,
        })


class MockChannel:
    """Mock AMQP Channel"""

    def __init__(self, exchange: MockExchange):
        self.exchange = exchange
        self.is_closed = False

    async def declare_exchange(self, name: str, type: Any, durable: bool):
        return self.exchange

    async def declare_queue(self, name: str, durable: bool):
        class MockQueue:
            async def bind(self, exchange, routing_key):
                pass
        return MockQueue()

    async def close(self):
        self.is_closed = True


@pytest.fixture
def mock_rabbitmq_publisher():
    """Tạo instance RabbitMQPublisher sử dụng MockExchange"""
    exchange = MockExchange()
    channel = MockChannel(exchange)
    publisher = RabbitMQPublisher(
        exchange_name=DEFAULT_EXCHANGE,
        queue_name=DEFAULT_QUEUE,
        channel=channel,
        exchange=exchange,
    )
    return publisher, exchange


@pytest.fixture(scope="module")
def client():
    """Khởi tạo TestClient nạp sẵn Lifespan"""
    with TestClient(app) as test_client:
        yield test_client


# ==============================================================================
# 1. Tests cho Định dạng Sự kiện & Xuất bản Message
# ==============================================================================

@pytest.mark.anyio
async def test_rabbitmq_publisher_message_schema(mock_rabbitmq_publisher):
    """Kiểm tra cấu trúc và nội dung sự kiện ai.risk.detected được phát sang RabbitMQ"""
    publisher, exchange = mock_rabbitmq_publisher

    pond_id = "pond-critical-1"
    ok = await publisher.publish_risk_alert(
        pond_id=pond_id,
        risk_level="CRITICAL",
        metric="dissolved_oxygen",
        predicted_value=2.45,
        action_suggestion="Bật toàn bộ quạt nước và tạt oxy viên khẩn cấp.",
        details={"ph": 7.4, "temp": 30.5},
    )

    assert ok is True
    assert len(exchange.published_messages) == 1

    msg = exchange.published_messages[0]
    assert msg["routing_key"] == ROUTING_KEY_RISK_DETECTED
    assert msg["content_type"] == "application/json"

    payload = msg["payload"]
    assert payload["event"] == "ai.risk.detected"
    assert payload["pond_id"] == pond_id
    assert payload["risk_level"] == "HIGH"
    assert payload["predicted_metric"] == "dissolved_oxygen"
    assert payload["predicted_value"] == 2.45
    assert "oxy viên" in payload["action_suggestion"]
    assert "timestamp" in payload
    assert payload["details"]["temp"] == 30.5


# ==============================================================================
# 2. Tests cho Graceful Degradation khi RabbitMQ Offline
# ==============================================================================

@pytest.mark.anyio
async def test_rabbitmq_offline_graceful_degradation():
    """
    Quy tắc Chịu lỗi (Resilience):
    Nếu RabbitMQ broker offline hoặc chưa bật, hệ thống tuyệt đối không làm crash API.
    """
    # Trỏ tới cổng không tồn tại với timeout ngắn
    offline_pub = RabbitMQPublisher(rabbitmq_url="amqp://guest:guest@localhost:9999/")

    # connect() không raise exception, trả về False
    connected = await offline_pub.connect()
    assert connected is False

    # ping() trả về False
    assert await offline_pub.ping() is False

    # publish_risk_alert() trả về False an toàn, không block hay ném lỗi
    ok = await offline_pub.publish_risk_alert(
        pond_id="pond-offline",
        risk_level="HIGH",
        metric="do_min",
        predicted_value=3.2,
        action_suggestion="Kiểm tra môi trường",
    )
    assert ok is False

    # close() an toàn
    await offline_pub.close()


class ClosableConnection:
    def __init__(self, channel=None):
        self.channel_instance = channel
        self.is_closed = False

    async def channel(self):
        return self.channel_instance

    async def close(self):
        self.is_closed = True


class HangingSetupChannel:
    def __init__(self):
        self.is_closed = False

    async def declare_exchange(self, *args, **kwargs):
        await asyncio.Event().wait()

    async def close(self):
        self.is_closed = True


@pytest.mark.asyncio
async def test_rabbitmq_connect_refused_returns_quickly(monkeypatch):
    async def refused(*args, **kwargs):
        raise ConnectionRefusedError("broker offline")

    monkeypatch.setattr("app.services.rabbitmq_publisher.aio_pika.connect_robust", refused)
    publisher = RabbitMQPublisher(connect_timeout_seconds=0.1)
    started = time.monotonic()

    assert await publisher.connect() is False
    assert time.monotonic() - started < 0.5
    assert await publisher.ping() is False


@pytest.mark.asyncio
async def test_rabbitmq_connect_timeout_cancels_shared_robust_task(monkeypatch):
    cancelled = asyncio.Event()
    calls = 0

    async def nonresponsive(*args, **kwargs):
        nonlocal calls
        calls += 1
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr("app.services.rabbitmq_publisher.aio_pika.connect_robust", nonresponsive)
    publisher = RabbitMQPublisher(connect_timeout_seconds=0.05)

    assert await publisher.connect() is False
    await asyncio.wait_for(cancelled.wait(), timeout=0.25)
    assert calls == 1
    assert publisher._connect_task is None
    assert await publisher.ping() is False


@pytest.mark.asyncio
async def test_rabbitmq_connect_timeout_closes_partially_initialized_resources(monkeypatch):
    channel = HangingSetupChannel()
    connection = ClosableConnection(channel)

    async def partially_connected(*args, **kwargs):
        return connection

    monkeypatch.setattr("app.services.rabbitmq_publisher.aio_pika.connect_robust", partially_connected)
    publisher = RabbitMQPublisher(connect_timeout_seconds=0.05)

    assert await publisher.connect() is False
    assert channel.is_closed is True
    assert connection.is_closed is True
    assert publisher._connection is None
    assert publisher._channel is None
    assert publisher._exchange is None


@pytest.mark.asyncio
async def test_rabbitmq_concurrent_offline_connects_share_one_attempt(monkeypatch):
    calls = 0

    async def nonresponsive(*args, **kwargs):
        nonlocal calls
        calls += 1
        await asyncio.Event().wait()

    monkeypatch.setattr("app.services.rabbitmq_publisher.aio_pika.connect_robust", nonresponsive)
    publisher = RabbitMQPublisher(connect_timeout_seconds=0.05)

    assert await asyncio.gather(*(publisher.connect() for _ in range(5))) == [False] * 5
    assert calls == 1
    assert publisher._connect_task is None


@pytest.mark.asyncio
async def test_rabbitmq_recovers_after_failed_connection(monkeypatch):
    attempts = 0
    exchange = MockExchange()
    channel = MockChannel(exchange)
    connection = ClosableConnection(channel)

    async def fail_then_connect(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionRefusedError("broker offline")
        return connection

    monkeypatch.setattr("app.services.rabbitmq_publisher.aio_pika.connect_robust", fail_then_connect)
    publisher = RabbitMQPublisher(connect_timeout_seconds=0.1)

    assert await publisher.connect() is False
    assert await publisher.connect() is True
    assert await publisher.ping() is True
    assert attempts == 2
    await publisher.close()


# ==============================================================================
# 3. Tests cho Tự động Đẩy Event qua API Endpoints khi Nguy Cơ Cao
# ==============================================================================

def test_api_feeding_forecast_publishes_event_on_critical_risk(client):
    """
    Khi gọi POST /api/v1/ai/forecast-feeding phát hiện DO < 3.0 (CRITICAL),
    API tự động xuất bản sự kiện ai.risk.detected sang RabbitMQ.
    """
    exchange = MockExchange()
    channel = MockChannel(exchange)
    app.state.rabbitmq_publisher = RabbitMQPublisher(channel=channel, exchange=exchange)

    pond_id = "pond-risk-feeding"
    payload = {
        "pond_id": pond_id,
        "shrimp_age": 60,
        "shrimp_weight": 20.0,
        "do_min": 2.2,  # Rất nguy hiểm -> Kích hoạt CRITICAL
        "tan_delta": 0.05,
        "rain_0600": 0.0,
        "previous_feed": 35.0,
        "water_exchange_ratio": 0.0,
    }

    response = client.post("/api/v1/ai/forecast-feeding", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["risk_level"] == "CRITICAL"

    # Kiểm tra RabbitMQ đã nhận được event
    assert len(exchange.published_messages) == 1
    event = exchange.published_messages[0]["payload"]
    assert event["event"] == "ai.risk.detected"
    assert event["pond_id"] == pond_id
    assert event["risk_level"] == "HIGH"
    assert event["predicted_metric"] == "feeding_intake"


def test_api_predict_publishes_event_on_danger(client):
    """
    Khi gọi POST /api/predict phát hiện chất lượng nước nguy cấp (DANGER / alert=True),
    API tự động xuất bản sự kiện ai.risk.detected sang RabbitMQ.
    """
    exchange = MockExchange()
    channel = MockChannel(exchange)
    app.state.rabbitmq_publisher = RabbitMQPublisher(channel=channel, exchange=exchange)

    pond_id = "pond-risk-water"
    payload = {
        "pondId": pond_id,
        "temperature": 34.0,
        "ph": 9.2,
        "salinity": 15.0,
        "dissolvedOxygen": 2.5,  # Tụt oxy nghiêm trọng -> DANGER
    }

    response = client.post("/api/predict", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["alert"] is True
    assert data["riskLevel"] == "DANGER"

    # Kiểm tra RabbitMQ đã nhận được event
    assert len(exchange.published_messages) == 1
    event = exchange.published_messages[0]["payload"]
    assert event["event"] == "ai.risk.detected"
    assert event["pond_id"] == pond_id
    assert event["risk_level"] == "HIGH"
    assert event["predicted_metric"] == "dissolved_oxygen"


def test_health_check_includes_rabbitmq_status(client):
    """Kiểm tra GET /health trả về trạng thái kết nối rabbitmq"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "rabbitmq" in data
    assert "connected" in data["rabbitmq"]
