"""AQS-104 contract coverage for stable AI risk-event identifiers."""

import json
from uuid import UUID

import pytest

from app.services.rabbitmq_publisher import RabbitMQPublisher


class RecordingExchange:
    def __init__(self):
        self.payloads = []

    async def publish(self, message, routing_key):
        self.payloads.append((json.loads(message.body.decode("utf-8")), routing_key))


def publisher():
    exchange = RecordingExchange()
    return RabbitMQPublisher(channel=object(), exchange=exchange), exchange


@pytest.mark.asyncio
async def test_risk_event_generates_uuid_and_includes_it_in_payload():
    publisher_instance, exchange = publisher()

    assert await publisher_instance.publish_risk_alert(
        pond_id="pond-1", risk_level="HIGH", metric="dissolved_oxygen",
        predicted_value=2.8, action_suggestion="Check aeration",
    )
    payload, routing_key = exchange.payloads[0]
    assert routing_key == "ai.risk.detected"
    assert str(UUID(payload["event_id"])) == payload["event_id"]


@pytest.mark.asyncio
async def test_retry_preserves_caller_event_id_while_independent_events_differ():
    publisher_instance, exchange = publisher()
    retry_id = "b4f73aed-1b4e-4bd2-8e1e-4da1bdf45788"
    arguments = dict(pond_id="pond-1", risk_level="HIGH", metric="do_min", predicted_value=2.8, action_suggestion="Check aeration")

    assert await publisher_instance.publish_risk_alert(**arguments, event_id=retry_id)
    assert await publisher_instance.publish_risk_alert(**arguments, event_id=retry_id)
    assert await publisher_instance.publish_risk_alert(**arguments)
    assert exchange.payloads[0][0]["event_id"] == retry_id
    assert exchange.payloads[1][0]["event_id"] == retry_id
    assert exchange.payloads[2][0]["event_id"] != retry_id


@pytest.mark.asyncio
async def test_invalid_event_id_is_rejected_without_publish():
    publisher_instance, exchange = publisher()
    assert not await publisher_instance.publish_risk_alert(
        pond_id="pond-1", risk_level="HIGH", metric="do_min", predicted_value=2.8,
        action_suggestion="Check aeration", event_id="not-a-uuid",
    )
    assert exchange.payloads == []
