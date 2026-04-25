"""Google Custom Search JSON API wrapper + direct search URL helper."""
from __future__ import annotations

import logging
import os
from urllib.parse import quote_plus

import aiohttp

logger = logging.getLogger(__name__)

_CSE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"


async def search_streaming_links(movie_name: str, num: int = 5) -> list[dict]:
    """Call Google CSE to find legal streaming pages for *movie_name*.

    Returns a (possibly empty) list of {'title', 'link', 'snippet'} dicts.
    Silently returns [] when credentials are absent (feature degrades gracefully).
    """
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    cse_id = os.environ.get("GOOGLE_CSE_ID", "")

    if not api_key or not cse_id:
        logger.warning("GOOGLE_API_KEY / GOOGLE_CSE_ID not set — skipping CSE call.")
        return []

    query = f"watch {movie_name} online streaming official"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                _CSE_ENDPOINT,
                params={"key": api_key, "cx": cse_id, "q": query, "num": num},
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

        return [
            {
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            }
            for item in data.get("items", [])
            if item.get("link", "").startswith("http")
        ]

    except Exception as exc:
        logger.error("Google CSE error: %s", exc)
        return []


def get_google_search_url(movie_name: str) -> str:
    """Return a direct Google search URL the user can click as a fallback."""
    q = quote_plus(f"watch {movie_name} online streaming official")
    return f"https://www.google.com/search?q={q}"
