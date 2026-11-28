"""
RabbitMQ Event-Driven Message Publisher cho AquaSense AI Microservice.
Sử dụng thư viện aio-pika (asyncio AMQP) để đẩy sự kiện cảnh báo sớm (AI Risk Detected).
Hỗ trợ Graceful Degradation: Không làm block hay gián đoạn API suy luận nếu RabbitMQ offline.
Do Backend-Integration-Agent chủ trì.
"""

from datetime import datetime, timezone
import asyncio
import json
import logging
from typing import Any, Dict, Optional
from uuid import UUID, uuid4
import aio_pika

from app.config import get_settings

logger = logging.getLogger("ai_service.services.rabbitmq")

DEFAULT_EXCHANGE = "shrimp.events"
DEFAULT_QUEUE = "ai_risk_alerts"
ROUTING_KEY_RISK_DETECTED = "ai.risk.detected"
EVENT_RISK_LEVELS = {"LOW": "LOW", "MEDIUM": "MEDIUM", "HIGH": "HIGH", "WARNING": "MEDIUM", "DANGER": "HIGH", "CRITICAL": "HIGH"}
DEFAULT_CONNECT_TIMEOUT_SECONDS = 2.0


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
        connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
    ):
        settings = get_settings()
        self.rabbitmq_url = rabbitmq_url or settings.rabbitmq_url
        self.exchange_name = exchange_name
        self.queue_name = queue_name

        self._connection: Optional[aio_pika.abc.AbstractRobustConnection] = None
        self._channel: Optional[aio_pika.abc.AbstractChannel] = channel
        self._exchange: Optional[aio_pika.abc.AbstractExchange] = exchange
        self._is_connected = False
        self._connect_timeout_seconds = connect_timeout_seconds
        self._connect_lock = asyncio.Lock()
        self._connect_task: Optional[asyncio.Task[bool]] = None

    @staticmethod
    def _safe_broker_url(url: str) -> str:
        """Return a log-safe AMQP URL without credentials."""
        try:
            from urllib.parse import urlsplit, urlunsplit

            parsed = urlsplit(url)
            host = parsed.hostname or "unknown-host"
            if parsed.port:
                host = f"{host}:{parsed.port}"
            return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, ""))
        except (TypeError, ValueError):
            return "<invalid-amqp-url>"

    @staticmethod
    async def _close_resource(resource: Optional[Any]) -> None:
        if resource is None:
            return
        try:
            if not getattr(resource, "is_closed", False):
                await resource.close()
        except Exception:
            logger.debug("[RabbitMQ] Ignored resource cleanup failure.", exc_info=True)

    async def _connect_once(self) -> bool:
        """Create and publish a fully initialized connection atomically.

        ``aio_pika.connect_robust`` retries internally. This coroutine is always
        owned by ``connect`` and is cancelled/awaited on the application timeout,
        so an offline broker cannot leave that retry loop in the background.
        """
        connection: Optional[Any] = None
        channel: Optional[Any] = None
        try:
            connection = await aio_pika.connect_robust(
                self.rabbitmq_url,
                timeout=self._connect_timeout_seconds,
            )
            channel = await connection.channel()
            exchange = await channel.declare_exchange(
                self.exchange_name,
                type=aio_pika.ExchangeType.TOPIC,
                durable=True,
            )
            queue = await channel.declare_queue(self.queue_name, durable=True)
            await queue.bind(exchange, routing_key="ai.risk.#")

            self._connection = connection
            self._channel = channel
            self._exchange = exchange
            self._is_connected = True
            return True
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "[RabbitMQ Warning] Broker unavailable at %s; using offline fallback.",
                self._safe_broker_url(self.rabbitmq_url),
                exc_info=True,
            )
            return False
        finally:
            if self._connection is not connection:
                await self._close_resource(channel)
                await self._close_resource(connection)

    async def _cancel_connect_task(self, task: asyncio.Task[bool]) -> None:
        """Cancel and drain an in-flight robust connect before returning offline."""
        async with self._connect_lock:
            if self._connect_task is task:
                self._connect_task = None
                if not task.done():
                    task.cancel()
        if not task.done():
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("[RabbitMQ] Connect task ended with an ignored error.", exc_info=True)

    async def connect(self) -> bool:
        """
        Khởi tạo kết nối robust tới RabbitMQ Broker, khai báo Topic Exchange và Queue.
        """
        if self._exchange is not None:
            self._is_connected = True
            return True

        async with self._connect_lock:
            if self._exchange is not None:
                self._is_connected = True
                return True
            if self._connect_task is None or self._connect_task.done():
                logger.info("[RabbitMQ] Connecting to AMQP Broker (%s)...", self._safe_broker_url(self.rabbitmq_url))
                self._connect_task = asyncio.create_task(self._connect_once())
            task = self._connect_task

        try:
            connected = await asyncio.wait_for(
                asyncio.shield(task), timeout=self._connect_timeout_seconds
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[RabbitMQ Warning] Connection attempt timed out after %.2fs; using offline fallback.",
                self._connect_timeout_seconds,
            )
            await self._cancel_connect_task(task)
            self._is_connected = False
            return False
        except asyncio.CancelledError:
            # A different concurrent caller may have timed out and cancelled the
            # shared task. That is an offline result, not a caller cancellation.
            if task.cancelled():
                self._is_connected = False
                return False
            raise
        except Exception:
            self._is_connected = False
            logger.warning("[RabbitMQ Warning] Connection attempt failed; using offline fallback.", exc_info=True)
            return False
        finally:
            async with self._connect_lock:
                if self._connect_task is task and task.done():
                    self._connect_task = None

        if not connected:
            self._is_connected = False
            return False
        logger.info("[RabbitMQ] Connected. Exchange: '%s', Queue: '%s'", self.exchange_name, self.queue_name)
        return True

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
        event_id: Optional[str] = None,
    ) -> bool:
        """
        Đẩy sự kiện AI Risk Detected vào RabbitMQ Exchange. A retry caller must
        pass its original event_id; a new business event gets a fresh UUIDv4.
        {
          "event": "ai.risk.detected",
          "event_id": "uuid-v4",
          "pond_id": "...",
          "risk_level": "HIGH",
          "predicted_metric": "dissolved_oxygen",
          "predicted_value": 2.8,
          "action_suggestion": "...",
          "details": {...},
          "timestamp": "..."
        }
        """
        resolved_event_id = event_id or str(uuid4())
        try:
            UUID(resolved_event_id)
        except (TypeError, ValueError):
            logger.warning("[RabbitMQ Publish Error] Invalid event_id for AI risk alert.")
            return False

        normalized_risk_level = EVENT_RISK_LEVELS.get(risk_level.upper())
        if normalized_risk_level is None:
            logger.warning("[RabbitMQ Publish Error] Invalid AI risk level for event.")
            return False

        payload = {
            "event": "ai.risk.detected",
            "event_id": resolved_event_id,
            "pond_id": pond_id,
            "risk_level": normalized_risk_level,
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
            task = self._connect_task
            if task is not None:
                await self._cancel_connect_task(task)
            await self._close_resource(self._channel)
            await self._close_resource(self._connection)
            logger.info("[RabbitMQ] Đã đóng kết nối RabbitMQ sạch sẽ.")
        except Exception as e:
            logger.debug(f"[RabbitMQ Close Exception] {e}")
        finally:
            self._connection = None
            self._channel = None
            self._exchange = None
            self._is_connected = False
