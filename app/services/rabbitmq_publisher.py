"""
RabbitMQ Event-Driven Message Publisher cho AquaSense AI Microservice.
Sử dụng thư viện aio-pika (asyncio AMQP) để đẩy sự kiện cảnh báo sớm (AI Risk Detected).
Hỗ trợ Graceful Degradation: Không làm block hay gián đoạn API suy luận nếu RabbitMQ offline.
Do Backend-Integration-Agent chủ trì.
"""

from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, Optional
import aio_pika

from app.config import get_settings

logger = logging.getLogger("ai_service.services.rabbitmq")

DEFAULT_EXCHANGE = "shrimp.events"
DEFAULT_QUEUE = "ai_risk_alerts"
ROUTING_KEY_RISK_DETECTED = "ai.risk.detected"


class RabbitMQPublisher:
    """
    Quản lý kết nối AMQP và xuất bản sự kiện AI Risk Detected sang RabbitMQ.
    """

    def __init__(
        self,
        rabbitmq_url: Optional[str] = None,
        exchange_name: str = DEFAULT_EXCHANGE,
        queue_name: str = DEFAULT_QUEUE,
        channel: Optional[Any] = None,
        exchange: Optional[Any] = None,
    ):
        settings = get_settings()
        self.rabbitmq_url = rabbitmq_url or settings.rabbitmq_url
        self.exchange_name = exchange_name
        self.queue_name = queue_name

        self._connection: Optional[aio_pika.abc.AbstractRobustConnection] = None
        self._channel: Optional[aio_pika.abc.AbstractChannel] = channel
        self._exchange: Optional[aio_pika.abc.AbstractExchange] = exchange
        self._is_connected = False

    async def connect(self) -> bool:
        """
        Khởi tạo kết nối robust tới RabbitMQ Broker, khai báo Topic Exchange và Queue.
        """
        if self._exchange is not None:
            self._is_connected = True
            return True

        try:
            logger.info(f"[RabbitMQ] Đang kết nối tới AMQP Broker ({self.rabbitmq_url})...")
            self._connection = await aio_pika.connect_robust(
                self.rabbitmq_url,
                timeout=2.0,
            )
            self._channel = await self._connection.channel()

            # Khai báo Topic Exchange durable
            self._exchange = await self._channel.declare_exchange(
                self.exchange_name,
                type=aio_pika.ExchangeType.TOPIC,
                durable=True,
            )

            # Khai báo Queue nhận cảnh báo
            queue = await self._channel.declare_queue(
                self.queue_name,
                durable=True,
            )

            # Ràng buộc Queue với Exchange theo routing key "ai.risk.#"
            await queue.bind(self._exchange, routing_key="ai.risk.#")

            self._is_connected = True
            logger.info(
                f"[RabbitMQ] Kết nối thành công! Exchange: '{self.exchange_name}', Queue: '{self.queue_name}'"
            )
            return True

        except Exception as e:
            logger.warning(
                f"[RabbitMQ Warning] Chưa thể kết nối RabbitMQ Broker ({e}). "
                "AI Service vẫn hoạt động ở chế độ offline fallback."
            )
            self._is_connected = False
            return False

    async def ping(self) -> bool:
        """Kiểm tra tính sẵn sàng của kết nối RabbitMQ"""
        if self._is_connected and (self._channel is not None or self._exchange is not None):
            return True
        return False

    async def publish_risk_alert(
        self,
        pond_id: str,
        risk_level: str,
        metric: str,
        predicted_value: float,
        action_suggestion: str,
        details: Optional[Dict[str, Any]] = None,
        routing_key: str = ROUTING_KEY_RISK_DETECTED,
    ) -> bool:
        """
        Đẩy sự kiện AI Risk Detected vào RabbitMQ Exchange:
        {
          "event": "ai.risk.detected",
          "pond_id": "...",
          "risk_level": "HIGH",
          "predicted_metric": "dissolved_oxygen",
          "predicted_value": 2.8,
          "action_suggestion": "...",
          "details": {...},
          "timestamp": "..."
        }
        """
        payload = {
            "event": "ai.risk.detected",
            "pond_id": pond_id,
            "risk_level": risk_level,
            "predicted_metric": metric,
            "predicted_value": round(float(predicted_value), 2),
            "action_suggestion": action_suggestion,
            "details": details or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Nếu chưa kết nối và chưa có exchange, thử kết nối nhanh
        if self._exchange is None:
            connected = await self.connect()
            if not connected or self._exchange is None:
                logger.warning(
                    f"[RabbitMQ Offline] Bỏ qua xuất bản sự kiện cảnh báo ao {pond_id} (Broker offline)."
                )
                return False

        try:
            body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            message = aio_pika.Message(
                body=body_bytes,
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            )

            await self._exchange.publish(message, routing_key=routing_key)
            logger.info(
                f"[RabbitMQ Published] Đã xuất bản sự kiện '{routing_key}' cho ao '{pond_id}' | "
                f"Level: {risk_level} | Metric: {metric}={predicted_value}"
            )
            return True

        except Exception as e:
            logger.warning(f"[RabbitMQ Publish Error] Ao={pond_id} - {e}")
            return False

    async def close(self) -> None:
        """Đóng kết nối RabbitMQ an toàn"""
        try:
            if self._channel is not None and not self._channel.is_closed:
                await self._channel.close()
            if self._connection is not None and not self._connection.is_closed:
                await self._connection.close()
            logger.info("[RabbitMQ] Đã đóng kết nối RabbitMQ sạch sẽ.")
        except Exception as e:
            logger.debug(f"[RabbitMQ Close Exception] {e}")
        finally:
            self._connection = None
            self._channel = None
            self._exchange = None
            self._is_connected = False
