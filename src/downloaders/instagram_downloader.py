"""Instagram media downloader — routes to Story (cookies) or Post (no cookies)."""

import re

from loguru import logger

from src.downloaders.base_downloader import (
    BaseDownloader,
    DownloadResult,
)
from src.downloaders.instagram_story_download import download_story
from src.downloaders.instagram_post_download import download_post


class InstagramDownloader(BaseDownloader):
    """Downloads Instagram media. Stories use cookies; Reels/Posts do not."""

    platform = "instagram"

    _STORY_PATTERN = re.compile(
        r"https?://(www\.)?instagram\.com/stories/.+", re.IGNORECASE
    )

    async def supports(self, url: str) -> bool:
        pattern = re.compile(
            r"https?://(www\.)?instagram\.com/(reel|p|stories|reels)/.+",
            re.IGNORECASE,
        )
        return bool(pattern.match(url))

    async def download(self, url: str) -> DownloadResult:
        """Route to Story downloader (cookies) or Post downloader (no cookies)."""
        if self._STORY_PATTERN.match(url):
            logger.info("[Instagram] Routing to Story downloader (with cookies)")
            return await download_story(url)

        logger.info("[Instagram] Routing to Post downloader (no cookies)")
        return await download_post(url)
