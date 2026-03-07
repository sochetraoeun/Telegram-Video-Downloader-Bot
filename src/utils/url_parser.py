"""URL parser to detect and classify video links."""

import re


PLATFORM_PATTERNS: dict[str, re.Pattern] = {
    "tiktok": re.compile(
        r"https?://(www\.|vm\.|vt\.)?tiktok\.com/.+", re.IGNORECASE
    ),
    "instagram": re.compile(
        r"https?://(www\.)?instagram\.com/(reel|p|stories|reels)/.+", re.IGNORECASE
    ),
}


def detect_platform(url: str) -> str | None:
    """Detect which platform a URL belongs to.

    Returns:
        Platform name ('tiktok' or 'instagram') or None if unsupported.
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
            results.append((url, platform))
    return results
