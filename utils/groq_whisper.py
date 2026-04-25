"""Groq Whisper audio transcription."""
from __future__ import annotations

import logging
import os

from groq import AsyncGroq

logger = logging.getLogger(__name__)

_client: AsyncGroq | None = None


def _get_client() -> AsyncGroq:
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=os.environ["GROQ_API_KEY"])
    return _client


async def transcribe_audio(audio_path: str) -> str:
    """Transcribe an OGG audio file using Groq Whisper large-v3.

    Returns the transcribed text string.
    """
    client = _get_client()

    with open(audio_path, "rb") as f:
        response = await client.audio.transcriptions.create(
            file=(os.path.basename(audio_path), f),
            model="whisper-large-v3",
            response_format="verbose_json",
            # No language forced — lets Whisper auto-detect Tamil / Tanglish
        )

    text: str = response.text if hasattr(response, "text") else str(response)
    logger.info("Transcription (%d chars): %s…", len(text), text[:80])
    return text
