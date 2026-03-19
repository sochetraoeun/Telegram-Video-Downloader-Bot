"""Application settings loaded from environment variables."""

import base64
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
    supported_platforms: str = Field(default="tiktok,instagram,youtube")

    # Instagram (optional — for Stories support)
    instagram_cookies_file: str | None = Field(
        default=None,
        description="Path to Netscape-format cookies.txt for Instagram (enables Stories)",
        validation_alias="INSTAGRAM_COOKIES_FILE",
    )
    instagram_cookies_base64: str | None = Field(
        default=None,
        description="Base64-encoded cookies.txt (for Railway/deploy — decoded to temp file at startup)",
        validation_alias="INSTAGRAM_COOKIES_BASE64",
    )

    # YouTube (optional — required by YouTube to bypass bot detection)
    youtube_cookies_file: str | None = Field(
        default=None,
        description="Path to Netscape-format cookies.txt for YouTube",
        validation_alias="YOUTUBE_COOKIES_FILE",
    )
    youtube_cookies_base64: str | None = Field(
        default=None,
        description="Base64-encoded cookies.txt for YouTube (for Railway/deploy)",
        validation_alias="YOUTUBE_COOKIES_BASE64",
    )

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
        s = Settings()
    except Exception as e:
        if "bot_token" in str(e).lower() and not os.environ.get("BOT_TOKEN"):
            raise RuntimeError(
                "BOT_TOKEN is required but not set. "
                "Add it in Railway → Variables → BOT_TOKEN = your_token_from_BotFather"
            ) from e
        raise

    # If INSTAGRAM_COOKIES_BASE64 is set (e.g. Railway), decode and write to temp file
    if s.instagram_cookies_base64 and not s.instagram_cookies_file:
        try:
            cookie_bytes = base64.b64decode(s.instagram_cookies_base64)
            cookie_path = "/tmp/instagram_cookies.txt"
            with open(cookie_path, "wb") as f:
                f.write(cookie_bytes)
            s = s.model_copy(update={"instagram_cookies_file": cookie_path})
        except Exception as e:
            raise RuntimeError(
                f"Failed to decode INSTAGRAM_COOKIES_BASE64: {e}. "
                "Ensure it's valid base64 from: base64 -i instagram_cookies.txt | tr -d '\\n'"
            ) from e

    # If YOUTUBE_COOKIES_BASE64 is set, decode and write to temp file
    if s.youtube_cookies_base64 and not s.youtube_cookies_file:
        try:
            cookie_bytes = base64.b64decode(s.youtube_cookies_base64)
            cookie_path = "/tmp/youtube_cookies.txt"
            with open(cookie_path, "wb") as f:
                f.write(cookie_bytes)
            s = s.model_copy(update={"youtube_cookies_file": cookie_path})
        except Exception as e:
            raise RuntimeError(
                f"Failed to decode YOUTUBE_COOKIES_BASE64: {e}. "
                "Ensure it's valid base64 from: base64 -i youtube_cookies.txt | tr -d '\\n'"
            ) from e

    return s


settings = _load_settings()
