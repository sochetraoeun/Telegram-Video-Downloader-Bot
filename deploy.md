# Deploy to Render — Step-by-Step Plan

Deploy your Telegram Media Downloader Bot to [Render](https://render.com).

This bot runs **long polling** (`run_polling`). On Render you have two deploy options:

- **Background Worker** (recommended, paid) — no HTTP port needed; runs 24/7.
- **Web Service** (works on Free tier) — requires a port to be open. This repo includes a tiny health server in `src/bot/main.py` (`start_health_server`) that listens on Render's `PORT` so the Web Service port scan succeeds.

> **Free Web Service caveat:** Render free Web Services **spin down after ~15 minutes of no HTTP traffic**. A polling bot has no incoming traffic, so it will sleep and stop responding. Use an external uptime pinger (e.g. [UptimeRobot](https://uptimerobot.com)) hitting `https://<your-service>.onrender.com/` every 5–10 minutes, or upgrade to **Starter** ($7/month).

### If deploy fails: “Port scan timeout / no open ports”

That message means the service is a **Web Service** (or **Private Service**). Render waits for something to listen on `PORT`; this bot never does.

**How to recognize it in logs (your bot may still start correctly):**

- You see `🟢 Bot is now running!` and then **`No open ports detected, continuing to scan...`** every minute until **Port scan timeout**.
- You see **`Setting WEB_CONCURRENCY=1 by default`** during deploy — that appears on **Web Services**, not on Background Workers.

So the failure is **not** your Dockerfile or `BOT_TOKEN`; it is the **service type** in Render.

**Fix:**

1. In the Render Dashboard, open the failing service → **Settings** → scroll to **Danger Zone** → **Delete** (or leave it and create a new service).
2. Click **New +** → **Background Worker** (not “Web Service”).
3. Connect the same repo, **Docker**, same `Dockerfile`, copy over **Environment** variables (especially `BOT_TOKEN`).
4. Deploy again.

You **cannot** turn an existing Web Service into a Background Worker; create a **Background Worker** from scratch.

After the worker is running, a `telegram.error.TimedOut` in logs often clears once the wrong service type is fixed (deploy was failing or restarting during the port check). If timeouts continue on a worker, try redeploying, confirm `BOT_TOKEN`, or pick a Render **region** closer to you; you can also raise HTTP timeouts in code (see `ApplicationBuilder` in `python-telegram-bot` docs).

---

## Part 1: What You Need (Before Starting)

| #   | What                   | How to Get                                                                                         |
| --- | ---------------------- | -------------------------------------------------------------------------------------------------- |
| 1   | **Render account**     | Sign up at [render.com](https://render.com)                                                        |
| 2   | **GitHub account**     | Sign up at [github.com](https://github.com) if you don't have one                                  |
| 3   | **Telegram Bot Token** | Message [@BotFather](https://t.me/BotFather) on Telegram → `/newbot` → follow prompts → copy token |
| 4   | **Project on GitHub**  | Push this project to a GitHub repository                                                           |

**Plan note:** Render’s **free** instance type is **not** available for background workers. You need at least **Starter** (or higher) for a worker that runs 24/7. See [Render pricing](https://render.com/pricing).

---

## Part 2: What to Do — Step by Step

### Step 1: Use the Dockerfile (recommended)

This repository already has a root `Dockerfile` that installs **ffmpeg**, **yt-dlp**, Python dependencies, and runs:

`python src/bot/main.py`

Render will build from this file when you choose **Docker** as the runtime. You do **not** need `nixpacks.toml` for Render (that file is for Nixpacks-based hosts such as Railway).

---

### Step 1.5: Run build test locally (optional but recommended)

**Option A: Docker build (matches Render)**

```bash
docker build -t telegram-bot .

docker run --env-file .env telegram-bot
```

**Option B: Run with Python directly**

```bash
# System deps: ffmpeg, yt-dlp (brew on macOS, apt on Linux)
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
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/TG-Project.git
git branch -M main
git push -u origin main
```

If it is already on GitHub, push any changes (including `render.yaml` if you use the Blueprint option below):

```bash
git add .
git commit -m "Configure Render deployment"
git push origin main
```

---

### Step 3: Create a Render Background Worker

1. Open the [Render Dashboard](https://dashboard.render.com) and sign in.
2. Click **New +** → **Background Worker**.
3. Connect your **GitHub** account and select this repository (and branch, usually `main`).
4. Configure the service:
   - **Name:** e.g. `telegram-video-bot`
   - **Language:** **Docker**
   - **Dockerfile path:** `./Dockerfile` (default if the file is at the repo root)
   - **Docker build context:** `.` (repo root)
   - **Docker Command:** leave empty so Render uses the `CMD` in your Dockerfile (`python src/bot/main.py`).
5. Choose an instance type (**Starter** or higher; **Free** is not available for workers).
6. Click **Create Background Worker**.

Render will build the image and start the worker.

**Optional — Blueprint:** If you prefer infrastructure-as-code, this repo can include `render.yaml`. In the dashboard go to **Blueprints** → **New Blueprint Instance**, connect the repo, and deploy. Set `BOT_TOKEN` when prompted (or add it under **Environment** after deploy).

---

### Step 4: Add your Bot Token (required)

> **Important:** Without `BOT_TOKEN`, the bot will exit with a validation error. Add it before relying on the deploy.

1. Open your **Background Worker** service in Render.
2. Go to **Environment**.
3. Add **Environment Variable**:
   - **Key:** `BOT_TOKEN`
   - **Value:** your token from BotFather
4. Save. Render will redeploy (or restart) the service.

---

### Step 5: Wait for the build and check logs

1. Open the **Logs** tab for the worker.
2. Wait for the Docker build to finish and the process to start.
3. Look for: `🟢 Bot is now running!`

If you see that, the bot process is live.

---

### Step 6: Test your bot

1. Open Telegram and find your bot.
2. Send `/start` — you should get the welcome message.
3. Send a supported link — the bot should download and send the media.

---

## Part 3: Optional — More Environment Variables

In Render → your worker → **Environment**, you can add (all optional unless noted):

| Variable                    | Example             | What it does                  |
| --------------------------- | ------------------- | ----------------------------- |
| `BOT_USERNAME`              | `your_bot_username` | Your bot's @username          |
| `MAX_FILE_SIZE_MB`          | `50`                | Max video size (default 50)   |
| `RATE_LIMIT_PER_MIN`        | `10`                | Downloads per user per minute |
| `SUPPORTED_PLATFORMS`       | `tiktok,instagram`  | Platforms to support          |
| `INSTAGRAM_COOKIES_BASE64`  | *(see below)*       | **Only for Stories** — Reels/Posts work without cookies |

### Instagram cookies (only for Stories)

Reels and Posts work without cookies. **Stories** require login — add cookies only if you want Story support.

1. Log into Instagram in your browser (Chrome or Firefox).
2. Export cookies using [Get cookies.txt](https://chromewebstore.google.com/detail/get-cookiestxt/bgaddhkoddajcdgocldbbfleckgcbcid) (Chrome) or [cookies.txt](https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/) (Firefox). Save as `instagram_cookies.txt`.
3. Encode: `base64 -i instagram_cookies.txt | tr -d '\n'`
4. In Render → **Environment**: `INSTAGRAM_COOKIES_BASE64` = the base64 string.

---

## Part 4: If Something Goes Wrong

| Problem                     | What to try                                                                 |
| --------------------------- | --------------------------------------------------------------------------- |
| `BOT_TOKEN` / `bot_token` error | Add `BOT_TOKEN` in Render → **Environment** (Step 4). No extra spaces.   |
| **Instagram Stories fail**  | Add `INSTAGRAM_COOKIES_BASE64` (see Part 3).                                |
| Build fails                 | Check **Logs** for the Docker build error.                                  |
| **Port scan timeout / bind to a port** | You created a **Web Service**. Delete it and create a **Background Worker** (see callout above). |
| Wrong service type          | Use a **Background Worker**, not a Web Service (no HTTP port for polling). |
| `telegram.error.TimedOut`   | Often caused by failed Web Service deploys; switch to a worker first. If it persists, check token and region. |
| Bot stops / billing         | Workers need a paid instance type for continuous running; check plan and billing. |

---

## Summary Checklist

- [ ] Render + GitHub accounts
- [ ] Telegram bot token from BotFather
- [ ] Repo pushed to GitHub (with root `Dockerfile`)
- [ ] New **Background Worker** on Render, runtime **Docker**
- [ ] `BOT_TOKEN` set in **Environment**
- [ ] Logs show `🟢 Bot is now running!`
- [ ] Test bot on Telegram

---

> **Done!** Your bot runs on Render as a Docker-based background worker. Pushes to the connected branch trigger new deploys (per your service settings).
