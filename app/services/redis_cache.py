"""
Redis Async Caching Service cho AquaSense AI Microservice.
Lưu trữ kết quả dự báo mới nhất với TTL 1800s (30 phút) giúp Web Portal và Mobile App truy xuất < 5ms.
Hỗ trợ Graceful Degradation: Hoạt động bền bỉ, không gây crash ứng dụng nếu Redis offline.
Do Backend-Integration-Agent chủ trì.
"""

from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, Optional
import redis.asyncio as aioredis

from app.config import get_settings

logger = logging.getLogger("ai_service.services.redis")

FEEDING_CACHE_PREFIX = "ai:forecast:feeding"
WATER_CACHE_PREFIX = "ai:forecast:water"
DEFAULT_CACHE_TTL = 1800  # 30 phút (đồng bộ với chu kỳ Cronjob NestJS)


class RedisCacheService:
    """
    Quản lý kết nối và thao tác bộ nhớ đệm Redis bất đồng bộ (asyncio).
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        default_ttl: int = DEFAULT_CACHE_TTL,
        client: Optional[aioredis.Redis] = None,
    ):
        settings = get_settings()
        self.redis_url = redis_url or settings.redis_url
        self.default_ttl = default_ttl
        self._client: Optional[aioredis.Redis] = client
        self._is_connected = False

    async def get_client(self) -> Optional[aioredis.Redis]:
        """Khởi tạo hoặc trả về thực thể Redis client bất đồng bộ (lazy initialization)"""
        if self._client is None:
            try:
                self._client = aioredis.from_url(
                    self.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2.0,
                    socket_timeout=2.0,
                )
            except Exception as e:
                logger.warning(f"[Redis Warning] Không thể kết nối Redis ({self.redis_url}): {e}")
                return None
        return self._client

    async def ping(self) -> bool:
        """Kiểm tra tính sẵn sàng của Redis Server"""
        try:
            client = await self.get_client()
            if client is None:
                return False
            res = await client.ping()
            self._is_connected = bool(res)
            return self._is_connected
        except Exception as e:
            logger.debug(f"[Redis Ping Offline] {e}")
            self._is_connected = False
            return False

    async def get_json(self, key: str) -> Optional[Dict[str, Any]]:
        """Lấy dữ liệu JSON từ cache theo key"""
        try:
            client = await self.get_client()
            if client is None:
                return None
            raw = await client.get(key)
            if raw:
                return json.loads(raw)
            return None
        except Exception as e:
            logger.warning(f"[Redis Get Error] Key={key} - {e}")
            return None

    async def set_json(
        self,
        key: str,
        data: Dict[str, Any],
        ttl: Optional[int] = None,
    ) -> bool:
        """Lưu trữ dữ liệu dạng JSON vào cache với thời gian sống (TTL)"""
        try:
            client = await self.get_client()
            if client is None:
                return False
            expire_sec = ttl if ttl is not None else self.default_ttl
            payload_str = json.dumps(data, ensure_ascii=False)
            await client.set(key, payload_str, ex=expire_sec)
            return True
        except Exception as e:
            logger.warning(f"[Redis Set Error] Key={key} - {e}")
            return False

    # ==========================================================================
    # Phương thức nghiệp vụ chuyên biệt theo thiết kế hệ thống
    # ==========================================================================

    def make_feeding_key(self, pond_id: str) -> str:
        """Sinh key lưu kết quả dự báo thức ăn theo ao"""
        clean_id = pond_id.strip() if pond_id else "default"
        return f"{FEEDING_CACHE_PREFIX}:{clean_id}"

    def make_water_key(self, pond_id: str) -> str:
        """Sinh key lưu kết quả dự báo chất lượng nước theo ao"""
        clean_id = pond_id.strip() if pond_id else "default"
        return f"{WATER_CACHE_PREFIX}:{clean_id}"

    async def get_feeding_forecast(self, pond_id: str) -> Optional[Dict[str, Any]]:
        """Đọc kết quả dự báo lượng thức ăn mới nhất từ Redis"""
        key = self.make_feeding_key(pond_id)
        return await self.get_json(key)

    async def set_feeding_forecast(
        self,
        pond_id: str,
        forecast_data: Dict[str, Any],
        ttl: Optional[int] = None,
    ) -> bool:
        """Ghi nhận kết quả dự báo lượng thức ăn mới nhất vào Redis"""
        key = self.make_feeding_key(pond_id)
        return await self.set_json(key, forecast_data, ttl=ttl)

    async def get_water_quality_forecast(self, pond_id: str) -> Optional[Dict[str, Any]]:
        """Đọc kết quả dự báo chất lượng nước NestJS mới nhất từ Redis"""
        key = self.make_water_key(pond_id)
        return await self.get_json(key)

    async def set_water_quality_forecast(
        self,
        pond_id: str,
        predict_data: Dict[str, Any],
        ttl: Optional[int] = None,
    ) -> bool:
        """Ghi nhận kết quả dự báo chất lượng nước mới nhất vào Redis"""
        key = self.make_water_key(pond_id)
        return await self.set_json(key, predict_data, ttl=ttl)

    async def close(self) -> None:
        """Đóng kết nối Redis client an toàn"""
        if self._client is not None:
            try:
                await self._client.aclose()
                logger.info("[Redis] Đã ngắt kết nối Redis client thành công.")
            except Exception as e:
                logger.debug(f"[Redis Close] {e}")
            finally:
                self._client = None
                self._is_connected = False
