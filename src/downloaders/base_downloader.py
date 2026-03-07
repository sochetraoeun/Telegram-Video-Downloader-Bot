"""Abstract base class for media downloaders."""

import io
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

from loguru import logger


class MediaType(Enum):
    VIDEO = "video"
    IMAGE = "image"
    IMAGES = "images"


@dataclass
class DownloadResult:
    """Result of a media download."""

    buffer: io.BytesIO
    filename: str
    file_size: int
    media_type: MediaType = MediaType.VIDEO
    caption: str | None = None
    thumbnail: bytes | None = None
    duration: int | None = None
    width: int | None = None
    height: int | None = None
    extra_buffers: list[io.BytesIO] = field(default_factory=list)


class BaseDownloader(ABC):
    """Abstract base class for platform-specific downloaders."""

    platform: str = "unknown"

    @abstractmethod
    async def download(self, url: str) -> DownloadResult:
        """Download media from the given URL into memory.

        Args:
            url: The media URL to download.

        Returns:
            DownloadResult with media bytes in a BytesIO buffer.
            For multi-image posts, extra_buffers holds additional images.

        Raises:
            DownloadError: If the download fails.
        """
        ...

    @abstractmethod
    async def supports(self, url: str) -> bool:
        """Check if this downloader supports the given URL."""
        ...


class DownloadError(Exception):
    """Raised when a download fails."""

    def __init__(self, message: str, platform: str = "unknown", retryable: bool = True):
        self.message = message
        self.platform = platform
        self.retryable = retryable
        super().__init__(message)
        logger.error(f"[{platform}] Download error: {message}")
