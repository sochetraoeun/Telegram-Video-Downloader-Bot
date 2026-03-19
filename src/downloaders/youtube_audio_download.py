"""YouTube audio extraction — convert to MP3 via yt-dlp + ffmpeg."""

import io
import asyncio

from loguru import logger

from src.downloaders.base_downloader import (
    DownloadResult,
    DownloadError,
    MediaType,
)


async def download_audio(
    url: str, info: dict, cookie_args: list[str] | None = None
) -> DownloadResult:
    """Extract audio from a YouTube video and return as MP3.

    Uses yt-dlp's built-in audio extraction with ffmpeg post-processing.
    Pipes the MP3 output directly to stdout for in-memory capture.
    """
    title = info.get("title") or info.get("fulltitle")
    duration = info.get("duration")

    try:
        cmd = [
            "yt-dlp",
            "--no-warnings",
            "--no-check-certificates",
            "--extract-audio",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "0",
            "--output",
            "-",
            "--quiet",
            *(cookie_args or []),
            url,
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=300
        )

        if process.returncode != 0:
            error_msg = stderr.decode().strip() if stderr else "Unknown error"
            raise DownloadError(
                f"Audio extraction failed: {error_msg}",
                platform="youtube",
            )

        if not stdout:
            raise DownloadError(
                "No audio data received",
                platform="youtube",
            )

        buffer = io.BytesIO(stdout)
        file_size = len(stdout)
        buffer.seek(0)

        safe_title = (title or "youtube_audio").replace("/", "_")[:60]

        logger.info(
            f"[YouTube] Extracted audio: {file_size / 1024 / 1024:.1f} MB"
        )

        return DownloadResult(
            buffer=buffer,
            filename=f"{safe_title}.mp3",
            file_size=file_size,
            media_type=MediaType.AUDIO,
            caption=title,
            duration=duration,
        )

    except asyncio.TimeoutError:
        raise DownloadError(
            "Audio extraction timed out (>300s)", platform="youtube"
        )
    except DownloadError:
        raise
    except Exception as e:
        raise DownloadError(f"Unexpected error: {e}", platform="youtube")
