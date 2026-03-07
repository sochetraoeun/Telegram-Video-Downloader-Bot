"""Application settings loaded from environment variables."""

import os

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Bot configuration from .env file or environment variables."""

    # Bot (BOT_TOKEN is the env var used by Railway, Docker, etc.)
    bot_token: str = Field(
        ...,
        description="Telegram bot token",
        validation_alias="BOT_TOKEN",
    )
    bot_username: str = Field(default="", description="Bot username")

    # Limits
    max_file_size_mb: int = Field(default=50, description="Max file size in MB")
    max_buffer_size_mb: int = Field(default=50, description="Max buffer size in MB")
    rate_limit_per_min: int = Field(default=10, description="Rate limit per minute")
    max_retry_attempts: int = Field(default=3, description="Max retry attempts")
    max_concurrent_downloads: int = Field(default=5, description="Max concurrent downloads")

    # Feature flags
    enable_inline_mode: bool = Field(default=False)
    enable_audio_extract: bool = Field(default=False)

    # Supported platforms
    supported_platforms: str = Field(default="tiktok,instagram")

    @property
    def platforms_list(self) -> list[str]:
        return [p.strip() for p in self.supported_platforms.split(",")]

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


# Singleton with helpful error when BOT_TOKEN is missing
def _load_settings() -> Settings:
    try:
        return Settings()
    except Exception as e:
        if "bot_token" in str(e).lower() and not os.environ.get("BOT_TOKEN"):
            raise RuntimeError(
                "BOT_TOKEN is required but not set. "
                "Add it in Railway → Variables → BOT_TOKEN = your_token_from_BotFather"
            ) from e
        raise


settings = _load_settings()
