"""Shared rate-limit handling: spacing between provider calls, and backoff when one refuses.

Providers meter tokens per minute, and this agent is token-heavy (a large tool schema plus tool
output accumulating across rounds), so back-to-back rounds can exhaust a small tier's budget. Two
mitigations live here: a minimum gap between consecutive provider calls, and a retry that waits for
however long the provider itself said to wait.
"""
import asyncio
import logging
import os
import re
import time

logger = logging.getLogger("orchestrator.ratelimit")

MIN_CALL_INTERVAL = float(os.getenv("PROVIDER_MIN_CALL_INTERVAL", "1.5"))
MAX_RATE_LIMIT_RETRIES = int(os.getenv("PROVIDER_RATE_LIMIT_RETRIES", "3"))
MAX_RETRY_WAIT = 60.0
_RETRY_BUFFER = 0.5

# Providers often state the wait in prose ("Please try again in 11.0625s") as well as in a header.
_RETRY_PROSE_RE = re.compile(r"try again in ([0-9.]+)\s*s", re.IGNORECASE)

_last_call_at = 0.0


async def space_calls():
    """Waits, if needed, so consecutive provider calls are not fired back to back."""
    global _last_call_at
    elapsed = time.monotonic() - _last_call_at
    if 0 < elapsed < MIN_CALL_INTERVAL:
        await asyncio.sleep(MIN_CALL_INTERVAL - elapsed)
    _last_call_at = time.monotonic()


def retry_delay(headers=None, body="", attempt=0):
    """How long to wait before retrying a rate-limited call. Prefers what the provider told us —
    the retry-after header, then any wait stated in the body — and falls back to exponential
    backoff."""
    if headers:
        raw = headers.get("retry-after") or headers.get("Retry-After")
        if raw:
            try:
                return min(float(raw) + _RETRY_BUFFER, MAX_RETRY_WAIT)
            except (TypeError, ValueError):
                pass

    match = _RETRY_PROSE_RE.search(str(body or ""))
    if match:
        try:
            return min(float(match.group(1)) + _RETRY_BUFFER, MAX_RETRY_WAIT)
        except ValueError:
            pass

    return min(2.0 ** attempt, MAX_RETRY_WAIT)


def is_rate_limited(status_code=None, error_text=""):
    if status_code == 429:
        return True
    text = str(error_text or "").lower()
    return "429" in text or "rate limit" in text or "too many requests" in text


async def wait_before_retry(delay, attempt):
    logger.warning(f"rate limited by provider, waiting {delay:.1f}s before retry {attempt + 1}")
    await asyncio.sleep(delay)
