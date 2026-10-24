from functools import lru_cache
from typing import Optional
from pydantic import Field

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
    HAS_PYDANTIC_SETTINGS = True
except ImportError:
    from pydantic import BaseSettings
    HAS_PYDANTIC_SETTINGS = False


class Settings(BaseSettings):
    """Cấu hình toàn hệ thống AI Service qua biến môi trường (.env)"""

    # Service Server
    app_env: str = Field(default="development", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")

    # TimescaleDB / PostgreSQL Database
    db_host: str = Field(default="localhost", alias="DB_HOST")
    db_port: int = Field(default=5432, alias="DB_PORT")
    db_user: str = Field(default="postgres", alias="DB_USER")
    db_pass: str = Field(default="LocalSecretPass!23", alias="DB_PASS")
    db_name: str = Field(default="shrimp_local_db", alias="DB_NAME")

    # Redis Cache
    redis_host: str = Field(default="localhost", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_password: Optional[str] = Field(default=None, alias="REDIS_PASSWORD")
    redis_db: int = Field(default=0, alias="REDIS_DB")
    redis_cache_ttl: int = Field(default=1800, alias="REDIS_CACHE_TTL")

    # RabbitMQ Event-Driven
    rabbitmq_host: str = Field(default="localhost", alias="RABBITMQ_HOST")
    rabbitmq_port: int = Field(default=5672, alias="RABBITMQ_PORT")
    rabbitmq_user: str = Field(default="admin", alias="RABBITMQ_USER")
    rabbitmq_pass: str = Field(default="admin123", alias="RABBITMQ_PASS")
    rabbitmq_exchange: str = Field(default="shrimp.events", alias="RABBITMQ_EXCHANGE")
    rabbitmq_queue: str = Field(default="ai_risk_alerts", alias="RABBITMQ_QUEUE")

    # Core Backend URL
    core_backend_url: str = Field(default="http://localhost:3000", alias="CORE_BACKEND_URL")

    if HAS_PYDANTIC_SETTINGS:
        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore",
        )
    else:
        class Config:
            env_file = ".env"
            env_file_encoding = "utf-8"
            extra = "ignore"

    @property
    def sync_database_url(self) -> str:
        """Đường dẫn kết nối đồng bộ SQLAlchemy tới TimescaleDB/PostgreSQL"""
        return f"postgresql://{self.db_user}:{self.db_pass}@{self.db_host}:{self.db_port}/{self.db_name}"

    @property
    def async_database_url(self) -> str:
        """Đường dẫn kết nối bất đồng bộ asyncpg tới TimescaleDB/PostgreSQL"""
        return f"postgresql+asyncpg://{self.db_user}:{self.db_pass}@{self.db_host}:{self.db_port}/{self.db_name}"

    @property
    def redis_url(self) -> str:
        """Đường dẫn kết nối Redis"""
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def rabbitmq_url(self) -> str:
        """Đường dẫn AMQP kết nối RabbitMQ"""
        return f"amqp://{self.rabbitmq_user}:{self.rabbitmq_pass}@{self.rabbitmq_host}:{self.rabbitmq_port}/"


@lru_cache()
def get_settings() -> Settings:
    """Trả về Singleton instance của Settings"""
    return Settings()
