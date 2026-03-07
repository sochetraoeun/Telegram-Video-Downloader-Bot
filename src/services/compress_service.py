"""In-memory video compression using ffmpeg."""

import io
import asyncio
import tempfile
import os

from loguru import logger

from src.config.settings import settings


async def compress_video(
    buffer: io.BytesIO,
    original_size: int,
    target_size_mb: int | None = None,
) -> io.BytesIO | None:
    """Compress video in-memory using ffmpeg.

    ffmpeg doesn't support pure pipe-to-pipe well for all formats,
    so we use temporary files but clean up immediately.

    Args:
        buffer: Input video BytesIO buffer.
        original_size: Original file size in bytes.
        target_size_mb: Target size in MB (defaults to MAX_FILE_SIZE_MB).

    Returns:
        Compressed BytesIO buffer, or None if compression fails.
    """
    if target_size_mb is None:
        target_size_mb = settings.max_file_size_mb

    target_size_bytes = target_size_mb * 1024 * 1024

    # If already under limit, no compression needed
    if original_size <= target_size_bytes:
        buffer.seek(0)
        return buffer

    logger.info(
        f"Compressing video: {original_size / 1024 / 1024:.1f}MB → target {target_size_mb}MB"
    )

    tmp_input = None
    tmp_output = None

    try:
        # Write input to temp file
        tmp_input = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        buffer.seek(0)
        tmp_input.write(buffer.read())
        tmp_input.flush()
        tmp_input.close()

        # Create output temp file
        tmp_output = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        tmp_output.close()

        # Calculate target bitrate (bits per second)
        # Assume ~60s max video, target slightly under limit
        target_bitrate = int((target_size_bytes * 8 * 0.9) / 60)

        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-i", tmp_input.name,
            "-y",  # Overwrite
            "-c:v", "libx264",
            "-b:v", str(target_bitrate),
            "-maxrate", str(target_bitrate),
            "-bufsize", str(target_bitrate * 2),
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-preset", "fast",
            tmp_output.name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        _, stderr = await asyncio.wait_for(
            process.communicate(), timeout=180
        )

        if process.returncode != 0:
            logger.error(f"ffmpeg compression failed: {stderr.decode()[:200]}")
            return None

        # Read compressed output into BytesIO
        result = io.BytesIO()
        with open(tmp_output.name, "rb") as f:
            result.write(f.read())

        compressed_size = result.tell()
        result.seek(0)

        if compressed_size > target_size_bytes:
            logger.warning(
                f"Compression insufficient: {compressed_size / 1024 / 1024:.1f}MB "
                f"(target: {target_size_mb}MB)"
            )
            result.close()
            return None

        logger.info(
            f"Compressed: {original_size / 1024 / 1024:.1f}MB → "
            f"{compressed_size / 1024 / 1024:.1f}MB"
        )
        return result

    except asyncio.TimeoutError:
        logger.error("ffmpeg compression timed out (>180s)")
        return None
    except Exception as e:
        logger.error(f"Compression error: {e}")
        return None
    finally:
        # Clean up temp files immediately
        if tmp_input and os.path.exists(tmp_input.name):
            os.unlink(tmp_input.name)
        if tmp_output and os.path.exists(tmp_output.name):
            os.unlink(tmp_output.name)
