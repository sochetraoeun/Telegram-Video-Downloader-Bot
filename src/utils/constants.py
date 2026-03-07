"""Application-wide constants."""

# Telegram limits
TELEGRAM_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

# Supported platforms
SUPPORTED_PLATFORMS = ("tiktok", "instagram")

# Bot messages
WELCOME_MESSAGE = """👋 **Welcome to Media Downloader Bot!**

Send me a link from **TikTok** or **Instagram** and I'll download the video or image for you instantly!

📌 **Supported platforms:**
• 🎵 TikTok (videos, no watermark + image slideshows)
• 📸 Instagram (Reels, Posts, Stories + image carousels)

Just paste a link and I'll handle the rest! 🚀"""

HELP_MESSAGE = """🆘 **How to use this bot:**

1️⃣ **Send a link** — Paste a TikTok or Instagram URL (video or image)
2️⃣ **Wait** — I'll download and send you the media
3️⃣ **Enjoy** — View it right here in Telegram!

📌 **Supported links:**
• `https://www.tiktok.com/...` (videos + image slideshows)
• `https://vm.tiktok.com/...`
• `https://www.instagram.com/reel/...` (videos)
• `https://www.instagram.com/p/...` (images, carousels, videos)

⚡ **Commands:**
• /start — Show welcome message
• /help — Show this help message
• /audio `<link>` — Extract audio only (MP3)

💡 **Tips:**
• You can send multiple links at once
• Works in group chats too!
• Videos and images are downloaded in the best available quality
• Image carousels are sent as albums"""
