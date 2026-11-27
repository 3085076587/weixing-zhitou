from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "投放数据看板"
    app_env: str = "dev"
    debug: bool = True
    api_prefix: str = "/api/v1"
    cors_origins: str = "*"
    database_url: str = "mysql+pymysql://root@127.0.0.1:3306/zhitou?charset=utf8mb4"
    redis_url: str = "redis://127.0.0.1:6379/3"
    detail_cache_interval_minutes: int = 10
    detail_cache_days: int = 7
    detail_cache_since: str = "2026-10-01"
    detail_cache_pause_seconds: float = 0.5
    zhitou_api_base: str = "https://mapi.ieh5.com"
    zhitou_token: str = ""
    secret_key: str = "zhitou-local"
    token_expire_minutes: int = 720
    init_admin_username: str = "admin"
    init_admin_password: str = "admin123"

    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
