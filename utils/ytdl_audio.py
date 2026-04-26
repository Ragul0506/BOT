"""yt-dlp audio downloader — downloads best audio and converts to MP3.

Requires:
  pip install yt-dlp>=2024.12.13
  apt-get install ffmpeg   (for MP3 conversion; already in Dockerfile)

Key design decisions vs original:
  - Fixed outtmpl "audio.%(ext)s" avoids glob failures on titles with
    special characters or long Unicode names.
  - Custom _YTDLLogger captures error strings without crashing on silence.
  - _YTDLCategoryError carries a category string so the caller can show
    a specific Tanglish/English error message rather than a generic one.
  - If ffmpeg post-processing fails (no .mp3 produced), falls back to
    sending the raw audio file (m4a / webm / opus).
  - noplaylist=True prevents accidental playlist downloads.
  - Three-tier download strategy:
      1. Chrome browser cookies + tv_embedded client (best: handles age-gated)
      2. tv_embedded client only (headless / Docker — no browser installed)
      3. Generic extractor (last resort for non-standard / embedded URLs)
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_BYTES = 45 * 1024 * 1024  # 45 MB — Telegram bot document limit is 50 MB

YT_URL_RE = re.compile(
    r"(https?://)?(www\.)?"
    r"(youtube\.com/(watch\?v=|shorts/)|youtu\.be/)"
    r"[A-Za-z0-9_\-]{11}",
    re.IGNORECASE,
)

# ── error categories & user messages ─────────────────────────────────────────

CATEGORY_MSGS: dict[str, str] = {
    "age_restricted": (
        "❌ இந்த வீடியோவை download பண்ண முடியாது.\n"
        "<i>Age-restricted — YouTube login தேவைப்படுகிறது.</i>\n\n"
        "வேற video try பண்ணுங்க."
    ),
    "private": (
        "❌ இந்த வீடியோவை download பண்ண முடியாது.\n"
        "<i>Private video — owner மட்டுமே பார்க்க முடியும்.</i>\n\n"
        "வேற video try பண்ணுங்க."
    ),
    "region_locked": (
        "❌ இந்த வீடியோவை download பண்ண முடியாது.\n"
        "<i>இந்த region-ல் available இல்லை (geo-restricted).</i>\n\n"
        "வேற video try பண்ணுங்க."
    ),
    "copyright": (
        "❌ இந்த வீடியோவை download பண்ண முடியாது.\n"
        "<i>Copyright issue — content owner blocked it.</i>\n\n"
        "வேற video try பண்ணுங்க."
    ),
    "live": (
        "❌ Live streams download பண்ண முடியாது.\n"
        "<i>Video end ஆன பிறகு மீண்டும் try பண்ணுங்க.</i>"
    ),
    "too_large": (
        "❌ Audio file too large (>{limit} MB).\n"
        "<i>சின்ன video try பண்ணுங்க.</i>"
    ),
    "unavailable": (
        "❌ இந்த வீடியோவை இப்போது download பண்ண முடியாது.\n"
        "<i>Video unavailable, deleted, or unsupported format.</i>\n\n"
        "வேற video try பண்ணுங்க."
    ),
}

CATEGORY_MSGS_EN: dict[str, str] = {
    "age_restricted": (
        "❌ Cannot download this video.\n"
        "<i>Age-restricted — YouTube login required.</i>\n\n"
        "Please try a different video."
    ),
    "private": (
        "❌ Cannot download this video.\n"
        "<i>Private video — only the owner can view it.</i>\n\n"
        "Please try a different video."
    ),
    "region_locked": (
        "❌ Cannot download this video.\n"
        "<i>Not available in this region (geo-restricted).</i>\n\n"
        "Please try a different video."
    ),
    "copyright": (
        "❌ Cannot download this video.\n"
        "<i>Copyright issue — blocked by content owner.</i>\n\n"
        "Please try a different video."
    ),
    "live": (
        "❌ Cannot download live streams.\n"
        "<i>Try again after the stream ends.</i>"
    ),
    "too_large": (
        "❌ Audio file too large (>{limit} MB).\n"
        "<i>Please try a shorter video.</i>"
    ),
    "unavailable": (
        "❌ Could not download this video.\n"
        "<i>Video unavailable, deleted, or unsupported format.</i>\n\n"
        "Please try a different video."
    ),
}


def get_category_msg(category: str, lang: str = "ta", **kwargs) -> str:
    """Return the user-facing error message for *category* in *lang*."""
    table = CATEGORY_MSGS_EN if lang == "en" else CATEGORY_MSGS
    text = table.get(category, table["unavailable"])
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return text


# ── custom yt-dlp logger ──────────────────────────────────────────────────────


class _YTDLLogger:
    """Captures yt-dlp log messages without silencing them completely."""

    def __init__(self) -> None:
        self.errors: list[str] = []

    def debug(self, msg: str) -> None:
        if msg.startswith("[download]") or msg.startswith("[ExtractAudio]"):
            logger.debug("yt-dlp: %s", msg.strip())

    def info(self, msg: str) -> None:
        logger.debug("yt-dlp info: %s", msg.strip())

    def warning(self, msg: str) -> None:
        logger.warning("yt-dlp warn: %s", msg.strip())
        self.errors.append(msg)

    def error(self, msg: str) -> None:
        logger.error("yt-dlp err: %s", msg.strip())
        self.errors.append(msg)


# ── error categorisation ──────────────────────────────────────────────────────


def _categorize(exc_msg: str, log_msgs: list[str]) -> str:
    combined = (exc_msg + " " + " ".join(log_msgs)).lower()
    if any(k in combined for k in ("age", "sign in", "confirm your age", "age-restricted", "18+")):
        return "age_restricted"
    if "private video" in combined:
        return "private"
    if any(k in combined for k in ("not available in your country", "region", "geo")):
        return "region_locked"
    if "copyright" in combined:
        return "copyright"
    if any(k in combined for k in ("live stream", "is live", "premiere")):
        return "live"
    return "unavailable"


# ── custom exception ──────────────────────────────────────────────────────────


class YTDLCategoryError(Exception):
    """Raised when yt-dlp fails; carries a *category* for the caller to use."""

    def __init__(self, category: str, original: Exception | None = None) -> None:
        self.category = category
        self.original = original
        super().__init__(category)


# ── data type ─────────────────────────────────────────────────────────────────


@dataclass
class AudioResult:
    path: str
    title: str
    artist: str
    duration_secs: int
    fmt: str  # actual audio format (mp3, m4a, webm, …)


# ── sync downloader ───────────────────────────────────────────────────────────

# Keywords that suggest a Chrome cookie extraction problem (not a YouTube error)
_COOKIE_ERR_HINTS = (
    "cookie", "chrome", "browser", "keyring",
    "unable to load cookies", "could not find",
)
# Errors where trying a different strategy definitely won't help
_DEFINITIVE_FAIL_HINTS = ("private video", "copyright")


def _sync_download(url: str, out_dir: str) -> AudioResult:
    import yt_dlp  # type: ignore[import]

    ytdl_log = _YTDLLogger()

    def _opts(**extra) -> dict:
        """Build a complete ydl_opts dict, merging any *extra* keys last."""
        return {
            # Prefer M4A → webm → any best audio
            "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
            # Fixed filename avoids issues with exotic Unicode titles
            "outtmpl": os.path.join(out_dir, "audio.%(ext)s"),
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "128",
                }
            ],
            "noplaylist": True,
            "max_filesize": MAX_BYTES,
            "socket_timeout": 30,
            "retries": 3,
            "logger": ytdl_log,
            "quiet": True,
            # tv_embedded client is not subject to YouTube's age-gate enforcement
            "extractor_args": {"youtube": {"player_client": ["tv_embedded", "web"]}},
            **extra,
        }

    # Three strategies, tried in order.  Each tuple is (label, opts).
    attempts = [
        # 1. Chrome cookies give access to age-restricted and login-gated videos.
        #    Skipped automatically if Chrome is not installed / profile unreadable.
        ("chrome-cookies+embedded", _opts(cookiesfrombrowser=("chrome",))),
        # 2. No cookies — works in headless / Docker environments.
        ("embedded-only",           _opts()),
        # 3. Force the generic extractor as a last resort for non-standard URLs.
        ("generic-extractor",       _opts(force_generic_extractor=True)),
    ]

    info = None
    last_exc: Exception | None = None

    for label, attempt_opts in attempts:
        try:
            with yt_dlp.YoutubeDL(attempt_opts) as ydl:
                info = ydl.extract_info(url, download=True)
            logger.info("yt-dlp succeeded [%s]", label)
            break
        except yt_dlp.utils.DownloadError as exc:
            last_exc = exc
            exc_lower = str(exc).lower()
            logger.warning("yt-dlp [%s] failed: %s", label, str(exc)[:150])
            # Private / copyright failures are definitive — other strategies won't help.
            if any(k in exc_lower for k in _DEFINITIVE_FAIL_HINTS):
                break
            # Cookie extraction failure on the first attempt → continue to next strategy.
            if label == "chrome-cookies+embedded" and any(k in exc_lower for k in _COOKIE_ERR_HINTS):
                logger.info("Chrome cookies unavailable; trying without cookies")
        except Exception as exc:
            last_exc = exc
            logger.error("yt-dlp [%s] unexpected: %s", label, exc, exc_info=True)
            break  # Unexpected errors are unlikely to be resolved by changing opts.

    if info is None:
        cat = _categorize(str(last_exc or ""), ytdl_log.errors)
        logger.error("yt-dlp all strategies exhausted [%s]: %s", cat, last_exc)
        raise YTDLCategoryError(cat, last_exc) from last_exc

    title: str = info.get("title") or "audio"
    artist: str = info.get("uploader") or info.get("channel") or "Unknown"
    duration: int = int(info.get("duration") or 0)

    # ── locate the output file ────────────────────────────────────────────────

    # Preferred: ffmpeg-converted MP3
    mp3_files = list(Path(out_dir).glob("*.mp3"))
    if mp3_files:
        path = str(mp3_files[0])
        fmt = "mp3"
    else:
        # ffmpeg post-processing failed or not installed → send raw format
        logger.warning(
            "No .mp3 found in %s; trying raw audio fallback. "
            "Is ffmpeg installed and in PATH?",
            out_dir,
        )
        fallback_exts = ["m4a", "webm", "opus", "ogg", "aac", "wav"]
        path = None
        fmt = "unknown"
        for ext in fallback_exts:
            candidates = list(Path(out_dir).glob(f"*.{ext}"))
            if candidates:
                path = str(candidates[0])
                fmt = ext
                logger.info("Fallback audio format: %s", fmt)
                break

        if path is None:
            raise YTDLCategoryError("unavailable")

    size = os.path.getsize(path)
    logger.info(
        "Audio ready: fmt=%s size=%.1f MB duration=%ds title=%s",
        fmt, size / 1_048_576, duration, title[:60],
    )

    if size > MAX_BYTES:
        os.unlink(path)
        raise ValueError(
            f"Audio file is {size // 1_048_576} MB — exceeds the "
            f"{MAX_BYTES // 1_048_576} MB limit."
        )

    return AudioResult(path=path, title=title, artist=artist, duration_secs=duration, fmt=fmt)


# ── async public API ──────────────────────────────────────────────────────────


async def download_audio(url: str) -> AudioResult:
    """Download audio from *url*, convert to MP3, return AudioResult.

    Raises:
        YTDLCategoryError: with .category in CATEGORY_MSGS keys
        ValueError:         when file exceeds MAX_BYTES (show size to user)
    """
    out_dir = tempfile.mkdtemp(prefix="ytdl_")
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, _sync_download, url, out_dir)
    except Exception:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise


def extract_yt_url(text: str) -> str | None:
    """Return the first YouTube URL found in *text*, or None."""
    m = YT_URL_RE.search(text)
    if not m:
        return None
    url = m.group(0)
    if not url.startswith("http"):
        url = "https://" + url
    return url
