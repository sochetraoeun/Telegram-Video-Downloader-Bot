# 🚀 Deploy to Railway — Step-by-Step Plan

Deploy your Telegram Media Downloader Bot to Railway.

---

## Part 1: What You Need (Before Starting)

| #   | What                   | How to Get                                                                                         |
| --- | ---------------------- | -------------------------------------------------------------------------------------------------- |
| 1   | **Railway account**    | Sign up at [railway.app](https://railway.app)                                                      |
| 2   | **GitHub account**     | Sign up at [github.com](https://github.com) if you don't have one                                  |
| 3   | **Telegram Bot Token** | Message [@BotFather](https://t.me/BotFather) on Telegram → `/newbot` → follow prompts → copy token |
| 4   | **Project on GitHub**  | Push this project to a GitHub repository                                                           |

---

## Part 2: What to Do — Step by Step

### Step 1: Add deployment config to your project

Create a file named `nixpacks.toml` in your project root (same folder as `requirements.txt`):

```toml
[phases.setup]
nixPkgs = ["python311", "ffmpeg", "yt-dlp"]

[phases.install]
cmds = ["pip install -r requirements.txt"]

[start]
cmd = "python src/bot/main.py"
```

This tells Railway to install Python, ffmpeg, yt-dlp, and how to run your bot.

---

### Step 1.5: Run build test locally (optional but recommended)

Before pushing to Railway, verify the build works on your machine.

**Option A: Docker build (recommended — matches Railway)**

```bash
# Build the image (same as Railway will do)
docker build -t telegram-bot .


# Run the bot (requires BOT_TOKEN in .env or pass it)
docker run --env-file .env telegram-bot
```

**Option B: Run with Python directly**

```bash
# Install system deps first: ffmpeg, yt-dlp (via brew on macOS, apt on Linux)
# brew install ffmpeg yt-dlp   # macOS
# sudo apt install ffmpeg && pip install yt-dlp   # Linux

pip install -r requirements.txt
python src/bot/main.py
```

If the bot starts and you see `🟢 Bot is now running!` in the logs, the build is good.

---

### Step 2: Push your project to GitHub

If your project is not on GitHub yet:

```bash
# Initialize git (if not already)
git init

# Add all files
git add .

# Commit
git commit -m "Add Railway deployment"

# Create repo on GitHub, then:
git remote add origin https://github.com/YOUR_USERNAME/TG-Project.git
git branch -M main
git push -u origin main
```

If it's already on GitHub, just add and push the new config:

```bash
git add nixpacks.toml
git commit -m "Add Railway deployment config"
git push origin main
```

---

### Step 3: Create a Railway project

1. Go to [railway.app](https://railway.app) and log in
2. Click **New Project**
3. Choose **Deploy from GitHub repo**
4. Authorize Railway to access your GitHub (if asked)
5. Select your **TG-Project** repository
6. Click **Deploy Now**

Railway will start building your project.

---

### Step 4: Add your Bot Token (required)

> **Important:** Without `BOT_TOKEN`, the bot will crash with "bot_token Field required". Add it before the first deploy.

1. In Railway, click on your **service** (the deployed app)
2. Go to the **Variables** tab
3. Click **+ New Variable**
4. Add:
   - **Variable:** `BOT_TOKEN`
   - **Value:** paste your Telegram bot token from BotFather
5. Click **Add**

Railway will redeploy automatically when you add variables.

---

### Step 5: Wait for the build and check logs

1. Go to the **Deployments** tab
2. Wait for the build to finish (green checkmark)
3. Click on the deployment → **View Logs**
4. Look for: `🟢 Bot is now running!`

If you see that, your bot is live.

---

### Step 6: Test your bot

1. Open Telegram
2. Find your bot (search by the username you gave BotFather)
3. Send `/start` — you should get the welcome message
4. Send a TikTok or Instagram link — the bot should download and send the media

---

## Part 3: Optional — Add More Variables

In Railway → Variables, you can add (all optional):

| Variable                    | Value               | What it does                  |
| --------------------------- | ------------------- | ----------------------------- |
| `BOT_USERNAME`              | `your_bot_username` | Your bot's @username          |
| `MAX_FILE_SIZE_MB`          | `50`                | Max video size (default 50)   |
| `RATE_LIMIT_PER_MIN`       | `10`                | Downloads per user per minute |
| `SUPPORTED_PLATFORMS`       | `tiktok,instagram`  | Platforms to support          |
| `INSTAGRAM_COOKIES_BASE64`  | *(see below)*       | **Only for Stories** — Reels/Posts work without cookies |

### Instagram cookies (only for Stories)

Reels and Posts work without cookies. **Stories** require login — add cookies only if you want Story support.

1. Log into Instagram in your browser (Chrome or Firefox).
2. Export cookies using [Get cookies.txt](https://chromewebstore.google.com/detail/get-cookiestxt/bgaddhkoddajcdgocldbbfleckgcbcid) (Chrome) or [cookies.txt](https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/) (Firefox). Save as `instagram_cookies.txt`.
3. Encode: `base64 -i instagram_cookies.txt | tr -d '\n'`
4. In Railway → Variables: `INSTAGRAM_COOKIES_BASE64` = the base64 string.

---

## Part 4: If Something Goes Wrong

| Problem                     | What to try                                                     |
| --------------------------- | --------------------------------------------------------------- |
| `bot_token` Field required  | Add `BOT_TOKEN` in Railway → Variables (Step 4). Must be set.   |
| **Instagram Stories fail**   | Add `INSTAGRAM_COOKIES_BASE64` (see Part 3). Stories require cookies; Reels/Posts do not. |
| Build fails                 | Check **Logs** for the error. Often: missing file or wrong path |
| `yt-dlp: command not found` | Use the Dockerfile option instead (see below)                   |
| `ffmpeg: command not found` | Same — use Dockerfile                                           |
| Bot doesn't respond         | Check `BOT_TOKEN` is correct and has no extra spaces            |
| Bot stops after a while     | Railway Hobby plan may sleep when idle; Pro keeps it running    |

---

## Alternative: Use Dockerfile Instead

If Nixpacks doesn't work, create a `Dockerfile` inyour project root:

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir yt-dlp

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

CMD ["python", "src/bot/main.py"]
```

Railway will detect the Dockerfile and use it instead of Nixpacks.

---

## Summary Checklist

- [ ] Have Railway + GitHub accounts
- [ ] Have Telegram bot token from BotFather
- [ ] Create `nixpacks.toml` in project root
- [ ] Run local build test (Docker or Python)
- [ ] Push project to GitHub
- [ ] Create Railway project → Deploy from GitHub
- [ ] Add `BOT_TOKEN` in Variables
- [ ] Check logs for `🟢 Bot is now running!`
- [ ] Test bot on Telegram

---

> **Done!** Your bot should now be running on Railway. Every push to `main` will trigger a new deployment.
