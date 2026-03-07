"""Media service — orchestrates download → RAM → send → free pipeline."""

import io
from loguru import logger

from src.downloaders.base_downloader import (
    BaseDownloader, DownloadResult, DownloadError, MediaType,
)
from src.downloaders.tiktok_downloader import TikTokDownloader
from src.downloaders.instagram_downloader import InstagramDownloader
from src.services.compress_service import compress_video
from src.config.settings import settings

TELEGRAM_MAX_PHOTO_SIZE = 10 * 1024 * 1024  # 10MB

_downloaders: dict[str, BaseDownloader] = {
    "tiktok": TikTokDownloader(),
    "instagram": InstagramDownloader(),
}


async def download_media(url: str, platform: str) -> DownloadResult:
    """Download media from URL into memory (BytesIO).

    Handles videos, single images, and multi-image posts.
    Compression is only applied to videos exceeding the file size limit.

    Args:
        url: The media URL.
        platform: The platform name ('tiktok' or 'instagram').

    Returns:
        DownloadResult with media bytes in RAM.

    Raises:
        DownloadError: If download fails after retries.
    """
    downloader = _downloaders.get(platform)
    if not downloader:
        raise DownloadError(
            f"No downloader for platform: {platform}",
            platform=platform,
            retryable=False,
        )

    last_error: Exception | None = None
    max_retries = settings.max_retry_attempts

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Download attempt {attempt}/{max_retries} for {platform}: {url}")
            result = await downloader.download(url)

            await _validate_result_size(result)
            return result

        except DownloadError as e:
            last_error = e
            if not e.retryable:
                raise
            logger.warning(f"Attempt {attempt} failed: {e.message}")
            if attempt < max_retries:
                continue
        except Exception as e:
            last_error = e
            logger.warning(f"Attempt {attempt} failed with unexpected error: {e}")
            if attempt < max_retries:
                continue

    raise DownloadError(
        f"All {max_retries} attempts failed. Last error: {last_error}",
        platform=platform,
        retryable=False,
    )


async def _validate_result_size(result: DownloadResult) -> None:
    """Check and compress media if needed. Modifies result in place."""
    if result.media_type == MediaType.VIDEO:
        await _handle_video_size(result)
    elif result.media_type == MediaType.IMAGE:
        _handle_image_size(result)
    elif result.media_type == MediaType.IMAGES:
        _handle_image_size(result)
        for buf in result.extra_buffers:
            if buf.getbuffer().nbytes > TELEGRAM_MAX_PHOTO_SIZE:
                logger.warning(
                    f"Carousel image exceeds 10MB ({buf.getbuffer().nbytes} bytes), "
                    "Telegram may reject it"
                )


async def _handle_video_size(result: DownloadResult) -> None:
    """Compress video if it exceeds the Telegram file size limit."""
    if result.file_size <= settings.max_file_size_bytes:
        return

    logger.info(f"File too large ({result.file_size} bytes), attempting compression...")
    compressed = await compress_video(result.buffer, result.file_size)

    if compressed and compressed is not result.buffer:
        result.buffer.close()
        result.buffer = compressed
        result.file_size = compressed.getbuffer().nbytes
        logger.info(f"Compressed to {result.file_size / 1024 / 1024:.1f} MB")
    elif not compressed:
        result.buffer.close()
        raise DownloadError(
            "Video too large even after compression",
            platform="unknown",
            retryable=False,
        )

    if result.file_size > settings.max_file_size_bytes:
        result.buffer.close()
        raise DownloadError(
            "Video exceeds 50MB limit",
            platform="unknown",
            retryable=False,
        )


def _handle_image_size(result: DownloadResult) -> None:
    """Warn if image exceeds Telegram's 10MB photo limit."""
    if result.file_size > TELEGRAM_MAX_PHOTO_SIZE:
        logger.warning(
            f"Image is {result.file_size / 1024 / 1024:.1f}MB — "
            "exceeds Telegram's 10MB photo limit, will send as document"
        )


# Keep backward compat alias
download_video = download_media


def free_buffer(buffer: io.BytesIO) -> None:
    """Safely free a BytesIO buffer."""
    try:
        buffer.close()
    except Exception:
        pass


def free_result(result: DownloadResult) -> None:
    """Free all buffers in a DownloadResult."""
    free_buffer(result.buffer)
    for buf in result.extra_buffers:
        free_buffer(buf)
