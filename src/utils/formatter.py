"""Message formatting utilities."""

import re

from src.downloaders.base_downloader import MediaType

_MARKDOWN_ESCAPE_RE = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")


def _escape_markdown(text: str) -> str:
    """Escape special Markdown characters in user-generated text."""
    return _MARKDOWN_ESCAPE_RE.sub(r"\\\1", text)


def format_downloading_message(platform: str, url: str) -> str:
    """Format the 'downloading' status message."""
    platform_emoji = {"tiktok": "🎵", "instagram": "📸"}
    emoji = platform_emoji.get(platform, "🎬")
    return f"{emoji} Downloading from **{platform.title()}**...\n⏳ Please wait..."


def format_success_message(media_type: MediaType, caption: str | None = None) -> str:
    """Format the success message after sending media."""
    labels = {
        MediaType.VIDEO: "video",
        MediaType.IMAGE: "image",
        MediaType.IMAGES: "images",
    }
    label = labels.get(media_type, "media")
    msg = f"✅ Downloaded {label}"
    if caption:
        safe_caption = _escape_markdown(caption)
        msg += f"\n\n📝 {safe_caption}"
    return msg


def format_error_message(error_type: str) -> str:
    """Format error messages based on error type."""
    messages = {
        "invalid_url": "❌ That doesn't look like a valid URL. Please send a TikTok or Instagram link.",
        "unsupported_platform": "🚧 Only **TikTok** and **Instagram** links are supported right now.",
        "stories_unsupported": "🔒 Instagram Stories require login and can't be downloaded. Try sending a Reel or Post link instead.",
        "download_failed": "😔 Download failed. The content might be private or unavailable. Please try again.",
        "too_large": "📏 Video is too large (>50MB) even after compression. Try a shorter video.",
        "rate_limited": "⏱️ Slow down! You've hit the rate limit. Please wait a moment.",
        "generic": "❌ Something went wrong. Please try again later.",
    }
    return messages.get(error_type, messages["generic"])


def format_file_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
