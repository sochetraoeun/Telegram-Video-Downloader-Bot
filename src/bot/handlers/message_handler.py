"""Message handler — detects media links and triggers downloads."""

import asyncio

from loguru import logger
from telegram import Update, InputMediaPhoto, InputMediaVideo
from telegram.ext import ContextTypes

from src.utils.url_parser import extract_supported_urls
from src.utils.formatter import (
    format_downloading_message,
    format_success_message,
    format_error_message,
    format_file_size,
)
from src.bot.reactions.reactor import react, check_thanks
from src.bot.middleware.rate_limit import is_rate_limited
from src.services.video_service import download_media, free_result
from src.downloaders.base_downloader import DownloadError, MediaType

_active_downloads: int = 0
_download_lock = asyncio.Lock()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages — detect links and download media."""
    if not update.message or not update.message.text:
        return

    text = update.message.text
    user = update.message.from_user
    chat_id = update.message.chat_id

    if await check_thanks(text):
        await react(update, "thanks")
        return

    supported_urls = extract_supported_urls(text)

    if not supported_urls:
        return

    if is_rate_limited(user.id):
        await update.message.reply_text(format_error_message("rate_limited"))
        return

    logger.info(f"Found {len(supported_urls)} supported link(s) from user {user.id}")

    for url, platform in supported_urls:
        await _process_media(update, context, url, platform, chat_id)


async def _process_media(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
    platform: str,
    chat_id: int,
) -> None:
    """Process a single media URL — download, send, free."""
    global _active_downloads

    await react(update, "processing")

    status_msg = await update.message.reply_text(
        format_downloading_message(platform, url),
        parse_mode="Markdown",
    )

    result = None
    try:
        async with _download_lock:
            _active_downloads += 1

        result = await download_media(url, platform)

        if result.media_type == MediaType.VIDEO:
            await _send_video(context, chat_id, result, status_msg)
        elif result.media_type == MediaType.IMAGE:
            await _send_photo(context, chat_id, result, status_msg)
        elif result.media_type == MediaType.IMAGES:
            await _send_media_group(context, chat_id, result, status_msg)

        await react(update, "complete")

        try:
            await status_msg.delete()
        except Exception:
            pass

        media_label = result.media_type.value
        logger.info(
            f"Sent {platform} {media_label} to user {update.message.from_user.id} "
            f"({format_file_size(result.file_size)})"
        )

    except DownloadError as e:
        await react(update, "error")
        error_type = "download_failed"
        if "too large" in e.message.lower():
            error_type = "too_large"

        try:
            await status_msg.edit_text(format_error_message(error_type))
        except Exception:
            await update.message.reply_text(format_error_message(error_type))

        logger.error(f"Download failed for {platform}: {e.message}")

    except Exception as e:
        await react(update, "error")
        try:
            await status_msg.edit_text(format_error_message("generic"))
        except Exception:
            await update.message.reply_text(format_error_message("generic"))

        logger.exception(f"Unexpected error for {platform}: {e}")

    finally:
        if result:
            free_result(result)

        async with _download_lock:
            _active_downloads -= 1


async def _send_video(context, chat_id: int, result, status_msg) -> None:
    """Send a video as native Telegram video."""
    try:
        await status_msg.edit_text(
            f"📤 Uploading **{format_file_size(result.file_size)}** video...",
            parse_mode="Markdown",
        )
    except Exception:
        pass

    await context.bot.send_video(
        chat_id=chat_id,
        video=result.buffer,
        filename=result.filename,
        caption=format_success_message(result.media_type, result.caption),
        parse_mode="Markdown",
        supports_streaming=True,
        width=result.width,
        height=result.height,
        duration=result.duration,
    )


async def _send_photo(context, chat_id: int, result, status_msg) -> None:
    """Send a single image as native Telegram photo."""
    try:
        await status_msg.edit_text(
            f"📤 Uploading image...",
            parse_mode="Markdown",
        )
    except Exception:
        pass

    await context.bot.send_photo(
        chat_id=chat_id,
        photo=result.buffer,
        filename=result.filename,
        caption=format_success_message(result.media_type, result.caption),
        parse_mode="Markdown",
    )


async def _send_media_group(context, chat_id: int, result, status_msg) -> None:
    """Send multiple images/videos as a Telegram media group (album)."""
    count = 1 + len(result.extra_buffers)
    try:
        await status_msg.edit_text(
            f"📤 Uploading **{count}** images...",
            parse_mode="Markdown",
        )
    except Exception:
        pass

    media_items = []

    # Telegram media groups: max 10 items, caption on first item only
    all_buffers = [result.buffer] + result.extra_buffers
    for i, buf in enumerate(all_buffers[:10]):
        buf.seek(0)
        caption = format_success_message(result.media_type, result.caption) if i == 0 else None
        media_items.append(
            InputMediaPhoto(
                media=buf,
                caption=caption,
                parse_mode="Markdown" if caption else None,
            )
        )

    if len(media_items) == 1:
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=all_buffers[0],
            caption=format_success_message(result.media_type, result.caption),
            parse_mode="Markdown",
        )
    else:
        await context.bot.send_media_group(
            chat_id=chat_id,
            media=media_items,
        )

    if count > 10:
        logger.warning(f"Carousel had {count} items, only sent first 10 (Telegram limit)")
