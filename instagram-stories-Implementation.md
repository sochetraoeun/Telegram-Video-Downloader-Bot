# Instagram Stories Support — Implementation Plan

This document outlines the steps to add Instagram Stories download support to the Telegram Video Downloader Bot. Stories require authentication (cookies) because Instagram treats them as private content.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Prerequisites](#2-prerequisites)
3. [How to Get Instagram Cookies](#3-how-to-get-instagram-cookies)
4. [Code Changes](#4-code-changes)
5. [Configuration](#5-configuration)
6. [Deployment](#6-deployment)
7. [Security & Privacy](#7-security--privacy)
8. [Testing Checklist](#8-testing-checklist)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Overview

### Current State

- **Reels, Posts, Carousels** → Supported (no login required)
- **Stories** → Rejected with message: _"Instagram Stories require login and can't be downloaded"_

### What Changes

- Add optional **cookie-based authentication** for Instagram
- When cookies are configured, **enable story downloads**
- When cookies are **not** configured, keep current behavior (reject story links)

### Story URL Format

```
https://www.instagram.com/stories/username/1234567890123456789
```

Stories can be:

- Single image
- Single video
- Multiple items (carousel-like) — yt-dlp returns a playlist

---

## 2. Prerequisites

Before you start, ensure you have:

| Item                  | Description                                                                              |
| --------------------- | ---------------------------------------------------------------------------------------- |
| **yt-dlp**            | Already in your project (`requirements.txt`). Ensure version supports Instagram stories. |
| **Instagram account** | A logged-in account (your own or a dedicated bot account)                                |
| **Cookies file**      | Netscape-format `cookies.txt` exported from a browser session (see Section 3)            |

---

## 3. How to Get Instagram Cookies

### Option A: Browser Extension (Easiest)

1. Install a cookie export extension:
   - **Chrome/Edge:** [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) or similar
   - **Firefox:** [cookies.txt](https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/)

2. Log in to [instagram.com](https://www.instagram.com) in your browser.

3. Open the extension and export cookies for `instagram.com`.

4. Save the file as `instagram_cookies.txt` (Netscape format).

### Option B: Manual Export (Advanced)

1. Log in to Instagram in your browser.
2. Open DevTools (F12) → Application → Cookies → `https://www.instagram.com`.
3. Copy relevant cookies (`sessionid`, `csrftoken`, etc.) into Netscape format.
4. Format: `domain\tinclude_subdomains\tpath\tsecure\texpiration\tname\tvalue`

### Option C: yt-dlp `--cookies-from-browser`

yt-dlp can read cookies directly from Chrome/Firefox. This requires the bot to run on a machine where the browser is installed and has an active Instagram session. **Not recommended for Railway/Docker** — use a cookies file instead.

---

## 4. Code Changes

### 4.1 Settings (`src/config/settings.py`)

Add optional Instagram cookies path:

```python
# Instagram (optional — for Stories support)
instagram_cookies_file: str | None = Field(
    default=None,
    description="Path to Netscape-format cookies.txt for Instagram (enables Stories)",
    validation_alias="INSTAGRAM_COOKIES_FILE",
)
```

- If `None` or empty → Stories remain unsupported (current behavior).
- If set → Pass `--cookies <path>` to yt-dlp for story URLs.

---

### 4.2 Instagram Downloader (`src/downloaders/instagram_downloader.py`)

#### Step 1: Inject settings

- Import `settings` from `src.config.settings`.
- Add a helper: `_get_cookies_args() -> list[str]` that returns `["--cookies", path]` if `settings.instagram_cookies_file` is set and the file exists, else `[]`.

#### Step 2: Change story handling in `download()`

**Current logic (lines 46–52):**

```python
if self._STORY_PATTERN.match(url):
    raise DownloadError("Instagram Stories require login...", ...)
```

**New logic:**

```python
if self._STORY_PATTERN.match(url):
    if not self._get_cookies_args():
        raise DownloadError(
            "Instagram Stories require login and are not supported. "
            "Try sending a Reel or Post link instead.",
            platform=self.platform,
            retryable=False,
        )
    # Fall through — treat as normal download with cookies
```

#### Step 3: Pass cookies to yt-dlp

Update every yt-dlp subprocess call to include cookie args when downloading **story URLs**:

- `_extract_info(url)` — add `*self._get_cookies_args()` only when URL is a story.
- `_download_video(url, info)` — add cookie args when URL is a story.
- `_download_carousel()` — add cookie args when the source URL is a story.

**Example for `_extract_info`:**

```python
args = [
    "yt-dlp",
    "--no-warnings",
    "--no-check-certificates",
    "--dump-json",
    "--quiet",
]
if self._STORY_PATTERN.match(url):
    args.extend(self._get_cookies_args())
args.append(url)

process = await asyncio.create_subprocess_exec(*args, ...)
```

#### Step 4: Story-specific download flow

Stories can be:

- **Single item** → Same as reel/post (video or image).
- **Multiple items** → yt-dlp returns `_type: "playlist"` with `entries`. Reuse `_download_carousel()` logic.

No new media types — reuse `MediaType.VIDEO`, `MediaType.IMAGE`, `MediaType.IMAGES`.

#### Step 5: Update `_extract_shortcode` (if needed)

Current regex: `instagram\.com/(?:p|reel|reels)/([A-Za-z0-9_-]+)`  
Stories use: `instagram.com/stories/username/1234567890` — different format.  
For stories, yt-dlp handles the URL directly; you likely **don’t need** to change `_extract_shortcode` since story downloads go through yt-dlp, not the HTTP fallback.

---

### 4.3 Formatter (`src/utils/formatter.py`)

Update the `stories_unsupported` message to be conditional if you add a "cookies not configured" vs "cookies invalid" distinction. For now, keep the existing message — it still applies when cookies are missing.

---

### 4.4 Error Handling

When cookies are configured but invalid/expired, yt-dlp may return:

- `"You need to log in to access this content"`
- `"Login required"`

Handle these by:

1. Catching the error in the download flow.
2. Returning a user-friendly message: _"Instagram session expired. Please update the cookies file."_

---

## 5. Configuration

### Local Development (`.env`)

```env
# Optional: Path to Instagram cookies (enables Stories)
INSTAGRAM_COOKIES_FILE=./instagram_cookies.txt
```

### Railway / Docker

1. **Option A — File in repo (not recommended for security):**  
   Add `instagram_cookies.txt` to `.gitignore` and use a secret file or build-time secret. Not ideal.

2. **Option B — Base64 env var (recommended):**  
   Encode the cookies file and pass as env var:

   ```bash
   base64 -i instagram_cookies.txt | tr -d '\n' | pbcopy
   ```

   Set `INSTAGRAM_COOKIES_BASE64` in Railway Variables. In code, at startup:
   - If `INSTAGRAM_COOKIES_BASE64` is set, decode and write to `/tmp/instagram_cookies.txt`
   - Set `instagram_cookies_file` to that path.

3. **Option C — Railway Volumes:**  
   If Railway supports volumes, mount a volume with the cookies file and set `INSTAGRAM_COOKIES_FILE` to the mounted path.

---

## 6. Deployment

### Checklist

- [ ] Export cookies (Section 3) and save as `instagram_cookies.txt`
- [ ] Add `INSTAGRAM_COOKIES_FILE` or `INSTAGRAM_COOKIES_BASE64` to your deployment config
- [ ] Implement code changes (Section 4)
- [ ] Test locally with a story link
- [ ] Deploy to Railway
- [ ] Test story download in production
- [ ] Add `instagram_cookies.txt` to `.gitignore` if storing locally

---

## 7. Security & Privacy

| Risk                  | Mitigation                                                             |
| --------------------- | ---------------------------------------------------------------------- |
| **Cookies in repo**   | Add `instagram_cookies.txt` to `.gitignore`. Never commit.             |
| **Session hijacking** | Use a dedicated Instagram account, not your personal one.              |
| **Cookie expiration** | Instagram sessions expire. Plan to refresh cookies every few weeks.    |
| **ToS**               | Downloading stories may violate Instagram's ToS. Use at your own risk. |

---

## 8. Testing Checklist

- [ ] **Without cookies:** Story link → Clear "Stories require login" message
- [ ] **With valid cookies:** Story (single image) → Image sent to user
- [ ] **With valid cookies:** Story (single video) → Video sent to user
- [ ] **With valid cookies:** Story (multiple items) → All items sent as media group
- [ ] **With expired cookies:** Story link → Friendly "session expired" message
- [ ] **Reels/Posts:** Still work without cookies (no regression)

---

## 9. Troubleshooting

| Issue                 | Possible cause                         | Fix                                                     |
| --------------------- | -------------------------------------- | ------------------------------------------------------- |
| "You need to log in"  | Cookies missing or expired             | Re-export cookies from a fresh browser session          |
| "Could not extract"   | Story URL format changed               | Check yt-dlp version; update if needed                  |
| Empty/corrupt file    | CDN or rate limit                      | Retry; consider rate limiting story downloads           |
| Cookie file not found | Wrong path in `INSTAGRAM_COOKIES_FILE` | Use absolute path or path relative to working directory |

---

## Summary

1. **Get cookies** — Export from browser (Section 3).
2. **Add config** — `INSTAGRAM_COOKIES_FILE` or `INSTAGRAM_COOKIES_BASE64` (Section 5).
3. **Update code** — Settings, downloader, cookie injection (Section 4).
4. **Deploy** — Use env vars, never commit cookies (Section 6).
5. **Maintain** — Refresh cookies when they expire (Section 7).
