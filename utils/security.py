"""Security utilities — rate limiting and input sanitisation.

Drop-in usage in handlers:
    from utils.security import rate_limiter, sanitize_user_text

    if not rate_limiter.is_allowed(update.effective_user.id):
        await msg.reply_text("⏳ கொஞ்சம் slow பண்ணுங்க! மீண்டும் try பண்ணுங்க.")
        return
"""
from __future__ import annotations

import html
import re
from collections import defaultdict
from time import monotonic


class _TokenBucket:
    """Sliding-window rate limiter (thread-safe via GIL for CPython)."""

    def __init__(self, max_calls: int, window_secs: float) -> None:
        self.max_calls = max_calls
        self.window = window_secs
        self._timestamps: dict[int, list[float]] = defaultdict(list)

    def is_allowed(self, user_id: int) -> bool:
        now = monotonic()
        cutoff = now - self.window
        ts = self._timestamps[user_id]
        # Evict expired timestamps
        self._timestamps[user_id] = [t for t in ts if t > cutoff]
        if len(self._timestamps[user_id]) >= self.max_calls:
            return False
        self._timestamps[user_id].append(now)
        return True

    def reset(self, user_id: int) -> None:
        self._timestamps.pop(user_id, None)


# Global limiter: 10 requests per 60 s per user.
# Covers voice notes, /movie, /ytmp3, /expense — all heavy API calls.
rate_limiter = _TokenBucket(max_calls=10, window_secs=60)

# Separate tighter limit for inline queries (triggered on every keystroke).
inline_rate_limiter = _TokenBucket(max_calls=5, window_secs=10)

# Limit for YouTube downloads (expensive): 3 per 5 min.
ytdl_rate_limiter = _TokenBucket(max_calls=3, window_secs=300)


def sanitize_user_text(text: str, max_len: int = 2000) -> str:
    """Truncate and strip null bytes from user-supplied text.

    Does NOT HTML-escape — callers decide when to escape for display.
    """
    # Remove null bytes (can break JSON parsing)
    text = text.replace("\x00", "")
    return text[:max_len]


# ── Prompt-injection delimiter helpers ───────────────────────────────────────

_DELIMITER_OPEN = "<user_input>"
_DELIMITER_CLOSE = "</user_input>"


def wrap_user_input(text: str, max_len: int = 2000) -> str:
    """Wrap user text in XML-style delimiters to resist prompt injection.

    The system prompts in groq_llm.py instruct the LLM never to follow
    instructions inside these tags.
    """
    clean = sanitize_user_text(text, max_len)
    return f"{_DELIMITER_OPEN}\n{clean}\n{_DELIMITER_CLOSE}"


# ── Safe error message for users ─────────────────────────────────────────────

_GENERIC_ERROR = (
    "😕 ஏதோ problem ஆச்சு! கொஞ்சம் நேரம் கழிச்சு மீண்டும் try பண்ணுங்க."
)


def user_safe_error(exc: Exception, *, log_prefix: str = "") -> str:
    """Return a generic Tanglish error string safe to show to users.

    Full details are expected to be logged by the caller.
    """
    return _GENERIC_ERROR


# ── Telegram callback data helpers ───────────────────────────────────────────

_SAFE_CB_RE = re.compile(r"[^\w\-:.]")


def safe_callback_data(prefix: str, *parts) -> str:
    """Build a callback_data string guaranteed to be ≤64 bytes.

    Encodes only the integer/safe-string parts; never embeds user content.
    All parts are cast to str and stripped of unsafe chars.
    """
    sanitised = [re.sub(_SAFE_CB_RE, "", str(p)) for p in parts]
    data = prefix + ":" + ":".join(sanitised)
    encoded = data.encode("utf-8")
    if len(encoded) > 64:
        # Truncate last part to fit
        data = data.encode("utf-8")[:64].decode("utf-8", errors="ignore")
    return data
