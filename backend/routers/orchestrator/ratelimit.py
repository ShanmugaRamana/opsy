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
# The budget has to outlast a per-minute quota window, because that is what a 429 usually is: the
# free Gemini tier meters requests and tokens per minute and asks for a wait in the tens of seconds,
# so a budget that gives up after a few seconds turns a quota that would have cleared on its own into
# a failed turn.
MAX_RATE_LIMIT_RETRIES = int(os.getenv("PROVIDER_RATE_LIMIT_RETRIES", "6"))
# Dropped connections, read timeouts and provider 5xx are worth retrying too, but they say nothing
# about how long to wait, so they get plain exponential backoff on a smaller budget than a 429.
MAX_TRANSIENT_RETRIES = int(os.getenv("PROVIDER_TRANSIENT_RETRIES", "2"))
MAX_RETRY_WAIT = 60.0
# Backoff for a 429 the provider gave no guidance on. It starts at a per-minute-quota scale rather
# than at one second: doubling from 1s spends the whole budget inside the window it is waiting out.
RATE_LIMIT_BASE_DELAY = float(os.getenv("PROVIDER_RATE_LIMIT_BASE_DELAY", "5.0"))
_RETRY_BUFFER = 0.5

# Providers often state the wait in prose ("Please try again in 11.0625s") as well as in a header.
_RETRY_PROSE_RE = re.compile(r"try again in ([0-9.]+)\s*s", re.IGNORECASE)
# Gemini states it in neither: its 429 body carries a google.rpc.RetryInfo detail
# ("retryDelay": "26s") and no retry-after header at all. Without this the only Gemini 429s we could
# time were the ones we guessed at.
_RETRY_INFO_RE = re.compile(r'"retryDelay"\s*:\s*"?([0-9.]+)s?"?', re.IGNORECASE)

_last_call_at = 0.0


async def space_calls():
    """Waits, if needed, so consecutive provider calls are not fired back to back."""
    global _last_call_at
    elapsed = time.monotonic() - _last_call_at
    if 0 < elapsed < MIN_CALL_INTERVAL:
        await asyncio.sleep(MIN_CALL_INTERVAL - elapsed)
    _last_call_at = time.monotonic()


def stated_retry_delay(headers=None, body=""):
    """The wait the provider itself asked for, in seconds, or None if it did not say. Unclamped, so
    callers can tell a wait that is worth taking from a quota window that will not clear today."""
    if headers:
        raw = headers.get("retry-after") or headers.get("Retry-After")
        if raw:
            try:
                return float(raw)
            except (TypeError, ValueError):
                pass

    text = str(body or "")
    for pattern in (_RETRY_INFO_RE, _RETRY_PROSE_RE):
        match = pattern.search(text)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                continue

    return None


def retry_delay(headers=None, body="", attempt=0):
    """How long to wait before retrying a rate-limited call. Prefers what the provider told us —
    the retry-after header, then any wait stated in the body — and falls back to exponential
    backoff."""
    stated = stated_retry_delay(headers, body)
    if stated is not None:
        return min(stated + _RETRY_BUFFER, MAX_RETRY_WAIT)

    return min(RATE_LIMIT_BASE_DELAY * 2.0 ** attempt, MAX_RETRY_WAIT)


def can_retry_rate_limit(attempt, headers=None, body=""):
    """Whether a 429 is worth waiting out at all.

    Two ways it is not: the attempt budget is spent, or the provider asked for longer than we are
    willing to hold the turn open for. The second is what separates a per-minute quota from a daily
    one - Gemini reports both as a 429, but a RetryInfo of hours will not clear during this turn, and
    sitting through the full budget only to fail anyway is worse for the user than being told now."""
    if attempt >= MAX_RATE_LIMIT_RETRIES:
        return False
    stated = stated_retry_delay(headers, body)
    return stated is None or stated <= MAX_RETRY_WAIT


def is_rate_limited(status_code=None, error_text=""):
    if status_code == 429:
        return True
    text = str(error_text or "").lower()
    return "429" in text or "rate limit" in text or "too many requests" in text


def is_transient_status(status_code):
    """A provider-side failure worth retrying: gateway and overload errors, but not 4xx, which
    would fail identically on a retry."""
    return status_code is not None and 500 <= status_code < 600


def transient_delay(attempt):
    """Backoff for failures that carry no retry-after guidance of their own."""
    return min(2.0 ** attempt, MAX_RETRY_WAIT)


async def wait_before_transient_retry(delay, attempt, reason):
    logger.warning(f"transient provider failure ({reason}), waiting {delay:.1f}s before retry {attempt + 1}")
    await asyncio.sleep(delay)


async def wait_before_retry(delay, attempt):
    logger.warning(f"rate limited by provider, waiting {delay:.1f}s before retry {attempt + 1}")
    await asyncio.sleep(delay)
