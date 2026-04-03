"""Instagram audio extraction — Reels, video posts, and video stories → MP3 via yt-dlp + ffmpeg."""

import asyncio
import glob
import io
import os
import tempfile

from loguru import logger

from src.downloaders.base_downloader import DownloadResult, DownloadError, MediaType


def _entry_is_image(entry: dict) -> bool:
    ext = entry.get("ext", "")
    vcodec = entry.get("vcodec", "none")
    formats = entry.get("formats", [])
    if ext in ("mp4", "webm", "mkv", "mov", "flv"):
        return False
    if vcodec not in ("none", None, ""):
        return False
    video_formats = [
        f for f in formats
        if f.get("vcodec", "none") not in ("none", None, "")
    ]
    if video_formats:
        return False
    if ext in ("jpg", "jpeg", "png", "webp"):
        return True
    return False


def info_has_extractable_audio(info: dict) -> bool:
    """False when metadata clearly indicates image-only; True if unknown (let yt-dlp try)."""
    if not info:
        return True
    if info.get("_type") == "playlist" and info.get("entries"):
        return any(not _entry_is_image(e) for e in info["entries"])
    return not _entry_is_image(info)


def _caption_and_duration(info: dict) -> tuple[str | None, int | None]:
    if not info:
        return None, None
    if info.get("_type") == "playlist" and info.get("entries"):
        for e in info["entries"]:
            if not _entry_is_image(e):
                cap = e.get("title") or e.get("description")
                if cap == "NA":
                    cap = None
                return cap, e.get("duration")
        cap = info.get("title")
        if cap == "NA":
            cap = None
        return cap, None
    cap = info.get("title") or info.get("description")
    if cap == "NA":
        cap = None
    return cap, info.get("duration")


async def download_instagram_audio(
    url: str,
    cookie_args: list[str],
    info: dict | None = None,
) -> DownloadResult:
    """Extract audio from an Instagram video URL as MP3 (first item if carousel)."""
    meta = info or {}
    if meta and not info_has_extractable_audio(meta):
        raise DownloadError(
            "This post has no video — only images, so there is no audio to extract.",
            platform="instagram",
            retryable=False,
        )

    caption, duration = _caption_and_duration(meta)
    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix="ig_audio_")
        output_template = os.path.join(tmp_dir, "audio.%(ext)s")

        cmd = [
            "yt-dlp",
            "--no-warnings",
            "--no-check-certificates",
            "--playlist-items", "1",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "--output", output_template,
            "--quiet",
            *cookie_args,
            url,
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        _, stderr = await asyncio.wait_for(
            process.communicate(), timeout=300
        )

        if process.returncode != 0:
            error_msg = stderr.decode().strip() if stderr else "Unknown error"
            raise DownloadError(
                f"Audio extraction failed: {error_msg[:500]}",
                platform="instagram",
            )

        mp3_files = glob.glob(os.path.join(tmp_dir, "*.mp3"))
        if not mp3_files:
            found = glob.glob(os.path.join(tmp_dir, "*"))
            if found:
                mp3_files = found
            else:
                raise DownloadError(
                    "No audio data received",
                    platform="instagram",
                )

        audio_path = mp3_files[0]
        with open(audio_path, "rb") as f:
            data = f.read()

        buffer = io.BytesIO(data)
        file_size = len(data)
        buffer.seek(0)

        safe_title = (caption or "instagram_audio").replace("/", "_")[:60]

        logger.info(
            f"[Instagram] Extracted audio: {file_size / 1024 / 1024:.1f} MB"
        )

        return DownloadResult(
            buffer=buffer,
            filename=f"{safe_title}.mp3",
            file_size=file_size,
            media_type=MediaType.AUDIO,
            caption=caption,
            duration=duration,
        )

    except asyncio.TimeoutError:
        raise DownloadError(
            "Audio extraction timed out (>300s)", platform="instagram"
        )
    except DownloadError:
        raise
    except Exception as e:
        raise DownloadError(f"Unexpected error: {e}", platform="instagram")
    finally:
        if tmp_dir and os.path.exists(tmp_dir):
            for f in glob.glob(os.path.join(tmp_dir, "*")):
                try:
                    os.unlink(f)
                except OSError:
                    pass
            try:
                os.rmdir(tmp_dir)
            except OSError:
                pass
