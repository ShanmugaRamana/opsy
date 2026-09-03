"""Runs an Ollama model pull as a background task, reporting progress through download_state.

The task - not any one WS connection - owns the transfer's lifetime (see download_state.py's
docstring): a client disconnecting does not stop the pull, and a page reload re-attaches to whatever
is already in flight. Percent, speed and ETA are computed from the sum of every digest layer Ollama
reports, not just the current one, so a multi-layer pull shows real whole-download progress instead of
resetting at each layer boundary.
"""
import json
import logging
import time

import anyio
import httpx

from core.db import get_connection
from .catalog import BACKEND, get_entry
from . import download_state
from .environment import OLLAMA_BASE_URL
from .queries import mark_failed, mark_ready, start_download

logger = logging.getLogger("local-models")

# No read timeout: a multi-gigabyte pull over a slow link can legitimately take many minutes between
# chunks arriving. The connect timeout still fails fast if Ollama isn't there at all.
_PULL_TIMEOUT = httpx.Timeout(connect=5.0, read=None, write=30.0, pool=5.0)


class _Cancelled(Exception):
    pass


def _start_download_row_sync(model_key):
    conn = get_connection()
    try:
        start_download(conn, model_key)
        conn.commit()
    finally:
        conn.close()


def _mark_ready_sync(model_key, size_bytes):
    conn = get_connection()
    try:
        mark_ready(conn, model_key, size_bytes)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _mark_failed_sync(model_key, error):
    conn = get_connection()
    try:
        mark_failed(conn, model_key, error)
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


async def _try_mark_failed(model_key, error):
    """Best-effort: persisting the failure must never be able to stop the caller from reaching
    download_state.finish_error(), which is what actually reaches the WS client. `_mark_failed_sync`
    already guards its own commit, but `get_connection()` inside it can still raise (e.g. the DB is
    the reason this download failed in the first place), and an unguarded raise here would do the
    same silent-death-of-a-background-task thing this whole function exists to prevent."""
    try:
        await anyio.to_thread.run_sync(_mark_failed_sync, model_key, error)
    except Exception:
        logger.exception(f"local-models - could not persist failure for {model_key}")


async def run_download(model_key, cancel_event):
    """The background task body. Every exit path calls exactly one of download_state.finish_done /
    finish_error, mirroring the terminal-event guarantee the agent sockets already rely on.

    `cancel_event` is the one the caller got back from download_state.try_begin(): the slot is
    claimed before this task is even created, so nothing here - including the very first DB write, or
    a bad model_key - can fail without a download_state record to report itself against. A WS client
    that connects while that record is missing gets "No download in progress" and, per download.js,
    redirects straight back to /setup: exactly the "the download page doesn't open" symptom, and
    silently, since this is a background asyncio task with no request/response cycle to surface an
    unhandled exception through. Hence the whole body sits inside the try below.
    """
    entry = get_entry(model_key)
    # Only for the log lines in the failure paths below - the real lookup is inside the try, so an
    # unknown key is reported through download_state rather than raised into a bare task.
    tag = entry["tag"] if entry else model_key

    digest_totals = {}
    digest_completed = {}
    bytes_at_last_tick = 0
    time_at_last_tick = time.monotonic()

    try:
        if entry is None:
            raise ValueError(f"unknown local model key: {model_key}")

        await anyio.to_thread.run_sync(_start_download_row_sync, model_key)

        logger.info(f"local-models - pulling {tag}")
        async with httpx.AsyncClient(timeout=_PULL_TIMEOUT) as client:
            async with client.stream(
                "POST", f"{OLLAMA_BASE_URL}/api/pull", json={"model": tag, "stream": True}
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode(errors="replace")
                    raise RuntimeError(f"{response.status_code}: {body[:300]}")

                async for line in response.aiter_lines():
                    if cancel_event.is_set():
                        raise _Cancelled()

                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if "error" in chunk:
                        raise RuntimeError(chunk["error"])

                    status = chunk.get("status", "")
                    digest = chunk.get("digest")
                    total = chunk.get("total")
                    completed = chunk.get("completed")

                    if digest and total is not None:
                        digest_totals[digest] = total
                        digest_completed[digest] = completed or 0

                    total_bytes = sum(digest_totals.values()) or None
                    downloaded_bytes = sum(digest_completed.values())

                    now = time.monotonic()
                    elapsed = now - time_at_last_tick
                    speed_mbps = None
                    eta_seconds = None
                    if elapsed >= 1.0:
                        delta_bytes = downloaded_bytes - bytes_at_last_tick
                        speed_mbps = round((delta_bytes / elapsed) / (1024 * 1024), 2)
                        if total_bytes and delta_bytes > 0:
                            remaining = max(total_bytes - downloaded_bytes, 0)
                            eta_seconds = round(remaining / (delta_bytes / elapsed))
                        bytes_at_last_tick = downloaded_bytes
                        time_at_last_tick = now

                    percent = round((downloaded_bytes / total_bytes) * 100, 1) if total_bytes else 0.0

                    download_state.update_progress(
                        phase=status,
                        percent=percent,
                        downloaded_bytes=downloaded_bytes,
                        total_bytes=total_bytes,
                        speed_mbps=speed_mbps,
                        eta_seconds=eta_seconds,
                        force=(status != "downloading"),
                    )

        final_size = sum(digest_totals.values()) or None
        await anyio.to_thread.run_sync(_mark_ready_sync, model_key, final_size)
        logger.info(f"local-models - {tag} ready ({final_size or 0} bytes)")
        download_state.finish_done(tag, BACKEND)

    except _Cancelled:
        logger.info(f"local-models - {tag} download cancelled")
        await _try_mark_failed(model_key, "cancelled")
        download_state.finish_error("Download cancelled.")

    except Exception as e:
        logger.error(f"local-models - {tag} failed: {e}")
        await _try_mark_failed(model_key, str(e))
        download_state.finish_error(str(e))
