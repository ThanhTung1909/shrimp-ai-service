"""Infrastructure adapters used only by explicitly isolated HTTP test processes."""

from __future__ import annotations

from typing import Any, Dict, Optional


class HttpTestRedisCache:
    """In-memory cache with the endpoint-facing Redis contract and no sockets."""

    def __init__(self) -> None:
        self._feeding: Dict[str, Dict[str, Any]] = {}
        self._water_quality: Dict[str, Dict[str, Any]] = {}
        self._water_quality_trajectory: Dict[str, Dict[str, Any]] = {}
        self._disease_risk: Dict[str, Dict[str, Any]] = {}

    async def ping(self) -> bool:
        return False

    async def get_feeding_forecast(self, pond_id: str) -> Optional[Dict[str, Any]]:
        value = self._feeding.get(pond_id)
        return dict(value) if value is not None else None

    async def set_feeding_forecast(
        self,
        pond_id: str,
        forecast_data: Dict[str, Any],
        ttl: Optional[int] = None,
    ) -> bool:
        del ttl
        self._feeding[pond_id] = dict(forecast_data)
        return True

    async def get_water_quality_forecast(self, pond_id: str) -> Optional[Dict[str, Any]]:
        value = self._water_quality.get(pond_id)
        return dict(value) if value is not None else None

    async def set_water_quality_forecast(
        self,
        pond_id: str,
        predict_data: Dict[str, Any],
        ttl: Optional[int] = None,
    ) -> bool:
        del ttl
        self._water_quality[pond_id] = dict(predict_data)
        return True

    async def set_water_quality_trajectory(
        self, pond_id: str, forecast_data: Dict[str, Any], ttl: Optional[int] = None,
    ) -> bool:
        self._water_quality_trajectory[pond_id] = dict(forecast_data)
        return True

    async def set_disease_risk_forecast(
        self, pond_id: str, forecast_data: Dict[str, Any], ttl: Optional[int] = None,
    ) -> bool:
        self._disease_risk[pond_id] = dict(forecast_data)
        return True

    async def close(self) -> None:
        self._feeding.clear()
        self._water_quality.clear()
        self._water_quality_trajectory.clear()
        self._disease_risk.clear()


class HttpTestRabbitMQPublisher:
    """No-op publisher that prevents isolated HTTP tests from reaching a broker."""

    async def connect(self) -> bool:
        return False

    async def ping(self) -> bool:
        return False

    async def publish_risk_alert(self, **_: Any) -> bool:
        return False

    async def close(self) -> None:
        return None
