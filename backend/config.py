"""
config.py — все настройки из .env.
StringSession = для деплоя на Render (без файла .session).
File session   = для локальной разработки.
"""
from __future__ import annotations
from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Telegram user account — my.telegram.org
    telegram_api_id: int
    telegram_api_hash: str
    telegram_phone: Optional[str] = None
    telegram_string_session: Optional[str] = None

    # Канал для мониторинга
    target_channel: str

    # Anthropic
    anthropic_api_key: str

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = False

    # TTL и очистка
    location_ttl_seconds: int = 7200
    cleanup_interval_seconds: int = 300

    # Nominatim
    nominatim_user_agent: str = "tcck-map/1.0"

    # SQLite
    db_path: str = "tcck_map.db"

    # Telethon reconnect
    reconnect_base_delay: float = 5.0
    reconnect_max_delay: float = 300.0
    reconnect_max_attempts: int = 0

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    def get_session(self):
        """StringSession если задан, иначе файловая сессия (локально)."""
        from telethon.sessions import StringSession
        if self.telegram_string_session:
            return StringSession(self.telegram_string_session)
        return "tcck_session"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
