"""YouTube Data API v3 — search for full movie video.

Requires env var YOUTUBE_API_KEY (Google Cloud project with YouTube Data API v3 enabled).
If the key is absent, search_full_movie() returns None gracefully.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Words in video titles that indicate a NON-full-movie upload.
_TRAILER_KEYWORDS = frozenset({
    "trailer", "teaser", "official trailer", "theatrical trailer",
    "promo", "clip", "deleted scene", "behind the scenes", "featurette",
    "interview", "making of", "bts", "sneak peek", "exclusive clip",
    "short film",
})


def youtube_api_configured() -> bool:
    """True when YOUTUBE_API_KEY is set."""
    return bool(os.environ.get("YOUTUBE_API_KEY", "").strip())


def _fmt_duration(secs: int) -> str:
    """Format seconds as M:SS or H:MM:SS string."""
    if not secs:
        return ""
    h, rem = divmod(int(secs), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _search_songs_api(query: str, api_key: str, max_results: int = 5) -> list[dict]:
    from googleapiclient.discovery import build  # type: ignore

    youtube = build("youtube", "v3", developerKey=api_key, cache_discovery=False)
    req = youtube.search().list(
        part="snippet",
        q=query,
        type="video",
        maxResults=max_results,
        fields="items(id/videoId,snippet/title,snippet/channelTitle)",
    )
    resp = req.execute()
    results = []
    for item in resp.get("items", []):
        vid = item.get("id", {}).get("videoId", "")
        title = item.get("snippet", {}).get("title", "")
        channel = item.get("snippet", {}).get("channelTitle", "")
        if vid:
            results.append({"video_id": vid, "title": title, "duration": 0, "channel": channel})
    return results


def _search_songs_ytdlp(query: str, max_results: int = 5) -> list[dict]:
    """Fallback search using yt-dlp (no API key required)."""
    import yt_dlp  # type: ignore

    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "noplaylist": False,
        "skip_download": True,
    }
    search_url = f"ytsearch{max_results}:{query}"
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(search_url, download=False) or {}
    except Exception as exc:
        logger.warning("yt-dlp song search failed: %s", exc)
        return []

    results = []
    for entry in (info.get("entries") or [])[:max_results]:
        if not entry:
            continue
        vid = entry.get("id") or ""
        title = entry.get("title") or "Unknown"
        duration = int(entry.get("duration") or 0)
        channel = entry.get("uploader") or entry.get("channel") or ""
        if vid:
            results.append({"video_id": vid, "title": title, "duration": duration, "channel": channel})
    return results


def search_songs(query: str, max_results: int = 5) -> list[dict]:
    """Search YouTube for songs. Returns list of {video_id, title, duration, channel}.

    Uses YouTube Data API if YOUTUBE_API_KEY is set, otherwise falls back to yt-dlp.
    Each result dict: {"video_id": str, "title": str, "duration": int, "channel": str}
    """
    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if api_key:
        try:
            results = _search_songs_api(query, api_key, max_results)
            if results:
                return results
        except Exception as exc:
            logger.warning("YouTube API song search failed: %s; falling back to yt-dlp", exc)
    return _search_songs_ytdlp(query, max_results)


def search_full_movie(title: str, year: str = "") -> Optional[str]:
    """Search YouTube for a full-length movie upload.

    Args:
        title: Movie title (English).
        year:  Release year string, e.g. "2022" (optional but improves results).
    Returns:
        YouTube watch URL string, or None if not found / API unavailable.
    """
    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        logger.debug("YOUTUBE_API_KEY not set — skipping full movie search")
        return None

    try:
        from googleapiclient.discovery import build  # type: ignore

        youtube = build("youtube", "v3", developerKey=api_key, cache_discovery=False)

        query_parts = [f'"{title}"']
        if year:
            query_parts.append(str(year))
        query_parts.append("full movie")
        query = " ".join(query_parts)

        request = youtube.search().list(
            part="snippet",
            q=query,
            type="video",
            videoDuration="long",   # >20 minutes — filters out most trailers
            maxResults=8,
            fields="items(id/videoId,snippet/title)",
        )
        response = request.execute()

        for item in response.get("items", []):
            video_title = item.get("snippet", {}).get("title", "").lower()
            video_id = item.get("id", {}).get("videoId", "")

            if not video_id:
                continue

            # Skip obvious non-full-movie uploads.
            if any(kw in video_title for kw in _TRAILER_KEYWORDS):
                logger.debug("YT full movie: skipping trailer-like video '%s'", video_title[:60])
                continue

            url = f"https://www.youtube.com/watch?v={video_id}"
            logger.info("YT full movie found for '%s': %s (%s)", title, url, video_title[:60])
            return url

        logger.info("YT full movie: no suitable result for '%s %s'", title, year)
        return None

    except Exception as exc:
        logger.warning("YouTube search failed for '%s': %s", title, exc)
        return None
