"""Instagram video download logic — single videos, carousel videos."""

import io
import asyncio

from loguru import logger

from src.downloaders.base_downloader import DownloadResult, DownloadError, MediaType


async def download_video(
    url: str, info: dict, get_cookies_args_fn
) -> DownloadResult:
    """Download video bytes into memory via yt-dlp."""
    try:
        args = [
            "yt-dlp",
            "--no-warnings",
            "--no-check-certificates",
            "--format",
            "best[filesize<50M]/best",
            "--output",
            "-",
            "--quiet",
        ]
        args.extend(get_cookies_args_fn(url))
        args.append(url)

        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=120
        )

        if process.returncode != 0:
            error_msg = stderr.decode().strip() if stderr else "Unknown error"
            raise DownloadError(
                f"yt-dlp failed: {error_msg}",
                platform="instagram",
            )

        if not stdout:
            raise DownloadError(
                "No video data received",
                platform="instagram",
            )

        buffer = io.BytesIO(stdout)
        file_size = len(stdout)
        buffer.seek(0)

        logger.info(
            f"[Instagram] Downloaded video: {file_size / 1024 / 1024:.1f} MB"
        )

        caption = info.get("title") or info.get("description")
        if caption == "NA":
            caption = None

        return DownloadResult(
            buffer=buffer,
            filename="instagram_video.mp4",
            file_size=file_size,
            media_type=MediaType.VIDEO,
            caption=caption,
        )

    except asyncio.TimeoutError:
        raise DownloadError(
            "Download timed out (>120s)", platform="instagram"
        )
    except DownloadError:
        raise
    except Exception as e:
        raise DownloadError(f"Unexpected error: {e}", platform="instagram")


async def download_video_bytes(url: str, get_cookies_args_fn) -> io.BytesIO:
    """Download a single video entry into a BytesIO buffer."""
    args = [
        "yt-dlp",
        "--no-warnings",
        "--no-check-certificates",
        "--format",
        "best[filesize<50M]/best",
        "--output",
        "-",
        "--quiet",
    ]
    args.extend(get_cookies_args_fn(url))
    args.append(url)

    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await asyncio.wait_for(
        process.communicate(), timeout=120
    )

    if process.returncode != 0 or not stdout:
        raise DownloadError(
            "Video download failed for carousel item",
            platform="instagram",
        )

    buf = io.BytesIO(stdout)
    buf.seek(0)
    return buf
