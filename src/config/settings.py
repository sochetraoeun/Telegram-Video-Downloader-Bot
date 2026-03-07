"""Application settings loaded from environment variables."""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Bot configuration from .env file."""

    # Bot
    bot_token: str = Field(..., description="Telegram bot token")
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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


# Singleton
settings = Settings()
