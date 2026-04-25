"""yt-dlp audio downloader — downloads best audio and converts to MP3.

Requires:
  pip install yt-dlp
  apt-get install ffmpeg   (for MP3 conversion)
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_BYTES = 45 * 1024 * 1024  # 45 MB (Telegram document limit is 50 MB)

YT_URL_RE = re.compile(
    r"(https?://)?(www\.)?"
    r"(youtube\.com/(watch\?v=|shorts/)|youtu\.be/)"
    r"[A-Za-z0-9_\-]{11}",
    re.IGNORECASE,
)


@dataclass
class AudioResult:
    path: str
    title: str
    artist: str
    duration_secs: int


def _sync_download(url: str, out_dir: str) -> AudioResult:
    import yt_dlp  # type: ignore[import]

    ydl_opts: dict = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(out_dir, "%(title)s.%(ext)s"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "128",  # lower quality = smaller file
            }
        ],
        "max_filesize": MAX_BYTES,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    # After post-processing the file is renamed to .mp3
    title: str = info.get("title") or "audio"
    artist: str = info.get("uploader") or info.get("channel") or "Unknown"
    duration: int = int(info.get("duration") or 0)

    # Find the downloaded mp3 file
    mp3_files = list(Path(out_dir).glob("*.mp3"))
    if not mp3_files:
        raise FileNotFoundError("yt-dlp did not produce an mp3 file.")

    mp3_path = str(mp3_files[0])
    size = os.path.getsize(mp3_path)
    if size > MAX_BYTES:
        os.unlink(mp3_path)
        raise ValueError(
            f"Audio file is {size // 1_048_576} MB — exceeds the {MAX_BYTES // 1_048_576} MB limit."
        )

    return AudioResult(path=mp3_path, title=title, artist=artist, duration_secs=duration)


async def download_audio(url: str) -> AudioResult:
    """Download audio from *url*, convert to MP3, return AudioResult."""
    out_dir = tempfile.mkdtemp(prefix="ytdl_")
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, _sync_download, url, out_dir)
    except Exception:
        # Clean up on error
        import shutil
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
