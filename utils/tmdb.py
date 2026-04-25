"""TMDB API wrapper – movie search, detail, trailer, credits."""
from __future__ import annotations

import asyncio
import logging
import os

import aiohttp

logger = logging.getLogger(__name__)

_BASE = "https://api.themoviedb.org/3"
_IMG_W500 = "https://image.tmdb.org/t/p/w500"
_IMG_W92 = "https://image.tmdb.org/t/p/w92"


def _api_key() -> str:
    key = os.environ.get("TMDB_API_KEY", "")
    if not key:
        raise RuntimeError("TMDB_API_KEY environment variable is not set.")
    return key


async def _get(session: aiohttp.ClientSession, path: str, **params) -> dict:
    params["api_key"] = _api_key()
    params.setdefault("language", "en-US")
    async with session.get(f"{_BASE}{path}", params=params) as resp:
        resp.raise_for_status()
        return await resp.json()


async def _fetch_extras(
    session: aiohttp.ClientSession, movie_id: int
) -> tuple[str | None, list[str], list[str]]:
    """Parallel-fetch videos + credits. Returns (trailer_url, genres, cast_names)."""
    videos_task = asyncio.create_task(_get(session, f"/movie/{movie_id}/videos"))
    credits_task = asyncio.create_task(_get(session, f"/movie/{movie_id}/credits"))
    videos_data, credits_data = await asyncio.gather(
        videos_task, credits_task, return_exceptions=True
    )

    # ── trailer ──────────────────────────────────────────────────────────────
    trailer_url: str | None = None
    if isinstance(videos_data, dict):
        for v in videos_data.get("results", []):
            if v.get("site") == "YouTube" and v.get("type") == "Trailer":
                trailer_url = f"https://www.youtube.com/watch?v={v['key']}"
                break

    # ── cast ─────────────────────────────────────────────────────────────────
    cast: list[str] = []
    if isinstance(credits_data, dict):
        cast = [
            m["name"]
            for m in credits_data.get("cast", [])[:3]
            if m.get("name")
        ]

    return trailer_url, cast


def _normalise(detail: dict, movie_id: int, trailer_url: str | None, cast: list[str]) -> dict:
    poster_path = detail.get("poster_path")
    genres = [g["name"] for g in detail.get("genres", [])[:3]]
    return {
        "id": movie_id,
        "title": detail.get("title") or "",
        "year": (detail.get("release_date") or "")[:4],
        "rating": round(float(detail.get("vote_average") or 0), 1),
        "overview": detail.get("overview") or "No overview available.",
        "poster_url": f"{_IMG_W500}{poster_path}" if poster_path else None,
        "thumb_url": f"{_IMG_W92}{poster_path}" if poster_path else None,
        "tmdb_url": f"https://www.themoviedb.org/movie/{movie_id}",
        "genres": genres,
        "cast": cast,
        "trailer_url": trailer_url,
    }


async def search_movie(query: str) -> dict | None:
    """Search TMDB; return full normalised dict (trailer, cast, genres) or None."""
    async with aiohttp.ClientSession() as session:
        search = await _get(session, "/search/movie", query=query, page=1)
        results = search.get("results", [])
        if not results:
            logger.info("TMDB: no results for '%s'", query)
            return None

        movie_id: int = results[0]["id"]

        detail_task = asyncio.create_task(_get(session, f"/movie/{movie_id}"))
        extras_task = asyncio.create_task(_fetch_extras(session, movie_id))
        detail, (trailer_url, cast) = await asyncio.gather(detail_task, extras_task)

    return _normalise(detail, movie_id, trailer_url, cast)


async def search_movies_multi(query: str, n: int = 5) -> list[dict]:
    """Return up to *n* light-weight movie dicts for inline queries (no extras)."""
    async with aiohttp.ClientSession() as session:
        search = await _get(session, "/search/movie", query=query, page=1)

    results = search.get("results", [])[:n]
    out = []
    for r in results:
        poster_path = r.get("poster_path")
        out.append(
            {
                "id": r["id"],
                "title": r.get("title") or "",
                "year": (r.get("release_date") or "")[:4],
                "rating": round(float(r.get("vote_average") or 0), 1),
                "overview": r.get("overview") or "",
                "poster_url": f"{_IMG_W500}{poster_path}" if poster_path else None,
                "thumb_url": f"{_IMG_W92}{poster_path}" if poster_path else None,
                "tmdb_url": f"https://www.themoviedb.org/movie/{r['id']}",
                "genres": [],
                "cast": [],
                "trailer_url": None,
            }
        )
    return out
