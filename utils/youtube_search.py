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
