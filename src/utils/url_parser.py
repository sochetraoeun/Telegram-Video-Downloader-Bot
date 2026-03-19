"""URL parser to detect and classify video links."""

import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse


PLATFORM_PATTERNS: dict[str, re.Pattern] = {
    "tiktok": re.compile(
        r"https?://(www\.|vm\.|vt\.)?tiktok\.com/.+", re.IGNORECASE
    ),
    "instagram": re.compile(
        r"https?://(www\.)?instagram\.com/(reel|p|stories|reels)/.+", re.IGNORECASE
    ),
    "youtube": re.compile(
        r"https?://(www\.|m\.)?(youtube\.com/(watch\?v=|shorts/|embed/|live/)[\w-]+|youtu\.be/[\w-]+)",
        re.IGNORECASE,
    ),
}

_YOUTUBE_STRIP_PARAMS = {"list", "start_radio", "index", "playnext", "pp"}


def _clean_youtube_url(url: str) -> str:
    """Strip playlist/radio params from YouTube watch URLs.

    Converts e.g.:
      https://www.youtube.com/watch?v=abc&list=RDabc&start_radio=1
    into:
      https://www.youtube.com/watch?v=abc
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""

    if "youtube.com" not in host and "youtu.be" not in host:
        return url

    params = parse_qs(parsed.query, keep_blank_values=True)
    cleaned = {k: v for k, v in params.items() if k not in _YOUTUBE_STRIP_PARAMS}
    new_query = urlencode(cleaned, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def detect_platform(url: str) -> str | None:
    """Detect which platform a URL belongs to.

    Returns:
        Platform name ('tiktok', 'instagram', or 'youtube') or None if unsupported.
    """
    for platform, pattern in PLATFORM_PATTERNS.items():
        if pattern.match(url):
            return platform
    return None


def extract_urls(text: str) -> list[str]:
    """Extract all URLs from a text message.

    Returns:
        List of URLs found in the text.
    """
    url_pattern = re.compile(
        r"https?://[^\s<>\"']+", re.IGNORECASE
    )
    return url_pattern.findall(text)


def extract_supported_urls(text: str) -> list[tuple[str, str]]:
    """Extract URLs and their platforms from text.

    Returns:
        List of (url, platform) tuples for supported platforms only.
    """
    urls = extract_urls(text)
    results = []
    for url in urls:
        platform = detect_platform(url)
        if platform:
            clean_url = _clean_youtube_url(url) if platform == "youtube" else url
            results.append((clean_url, platform))
    return results
