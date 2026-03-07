# Telegram Media Downloader Bot

A Telegram bot that downloads videos and images from **TikTok** and **Instagram** and sends them back as native Telegram media.

---

## How to Start (After Cloning)

### 1. Clone the project

```bash
git clone https://github.com/YOUR_USERNAME/TG-Project.git
cd TG-Project
```

### 2. Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate   # On macOS/Linux
# or: venv\Scripts\activate   # On Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Install FFmpeg (required for video/audio)

- **macOS:** `brew install ffmpeg`
- **Ubuntu/Debian:** `sudo apt install ffmpeg`
- **Windows:** Download from [ffmpeg.org](https://ffmpeg.org/download.html)

### 5. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and set your **BOT_TOKEN** (get it from [@BotFather](https://t.me/BotFather) on Telegram):

```
BOT_TOKEN=your-actual-bot-token-here
```

### 6. Run the bot

```bash
python src/bot/main.py
```

You should see `🟢 Bot is now running!` in the terminal. Open Telegram and message your bot.

---

## Supported Platforms

- **TikTok** — videos and image slideshows
- **Instagram** — Reels, Posts, Stories, and image carousels

---

## Commands

| Command         | Description                            |
| --------------- | -------------------------------------- |
| `/start`        | Welcome message                        |
| `/help`         | List commands and supported platforms  |
| `/audio <link>` | Extract audio from video (coming soon) |

---

## Deployment

See [deploy.md](deploy.md) for deploying to Railway.
