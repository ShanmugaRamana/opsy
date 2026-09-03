"""Tracks the single active local-model download and fans its progress out to any number of WS
viewers. Sibling of orchestrator/turn_state.py: single-process, in-memory, not persisted.

The pull itself is owned by a backend task (see download.py), not by any one socket - a WS client is
only ever a *viewer*. That's what lets a page reload re-attach to a live 9 GB pull instead of
restarting it, and it's why disconnecting a viewer must never cancel the transfer: only an explicit
POST /download/cancel does that.
"""
import asyncio
import logging
import time

logger = logging.getLogger("local-models")

STATUS_DOWNLOADING = "downloading"
STATUS_READY = "ready"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

# Live updates are throttled to this interval so a fast link doesn't flood every connected socket.
_MIN_EVENT_INTERVAL = 0.25

_state = None
_subscribers = []
_cancel_event = None
_last_publish_at = 0.0


def get_snapshot():
    return dict(_state) if _state is not None else None


def is_running():
    return _state is not None and _state["status"] == STATUS_DOWNLOADING


def try_begin(model_key, model_ref, display_name):
    """Claims the single download slot, returning the new cancel event - or None if a download is
    already running.

    Called by the request handler, before the task is created, and deliberately synchronous: the
    check and the claim happen with no await between them, so two near-simultaneous POSTs cannot both
    pass. Claiming inside the task body instead would leave a window, since a freshly created task
    does not run until a later loop tick - by which time a second request can already have looked at
    an unclaimed slot and started its own pull, orphaning the first one's cancel event.
    """
    global _state, _cancel_event, _last_publish_at
    if is_running():
        return None

    _state = {
        "model_key": model_key,
        "model_ref": model_ref,
        "display_name": display_name,
        "status": STATUS_DOWNLOADING,
        "phase": "starting",
        "percent": 0.0,
        "downloaded_bytes": 0,
        "total_bytes": None,
        "speed_mbps": None,
        "eta_seconds": None,
        "error": None,
    }
    _cancel_event = asyncio.Event()
    _last_publish_at = 0.0
    return _cancel_event


def cancel_requested():
    return _cancel_event is not None and _cancel_event.is_set()


def request_cancel():
    if _cancel_event is not None:
        _cancel_event.set()


def update_progress(*, force=False, **fields):
    """Updates the in-memory record and, unless throttled, fans a `progress` event out to every
    subscriber. `force=True` bypasses throttling for a phase change worth showing immediately."""
    global _last_publish_at
    if _state is None:
        return

    _state.update(fields)

    now = time.monotonic()
    if not force and (now - _last_publish_at) < _MIN_EVENT_INTERVAL:
        return
    _last_publish_at = now

    _publish({
        "type": "progress",
        "phase": _state["phase"],
        "percent": _state["percent"],
        "downloaded_bytes": _state["downloaded_bytes"],
        "total_bytes": _state["total_bytes"],
        "speed_mbps": _state["speed_mbps"],
        "eta_seconds": _state["eta_seconds"],
    })


def finish_done(model_id, provider):
    if _state is not None:
        _state["status"] = STATUS_READY
        _state["percent"] = 100.0
        _state["error"] = None
    _publish({
        "type": "done",
        "model_key": _state["model_key"] if _state else None,
        "model_id": model_id,
        "provider": provider,
    })


def finish_error(detail):
    if _state is not None:
        _state["status"] = STATUS_CANCELLED if cancel_requested() else STATUS_FAILED
        _state["error"] = detail
    _publish({"type": "error", "detail": detail})


def _publish(event):
    for queue in list(_subscribers):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("local-models - a download viewer queue is full, dropping an update")


def subscribe():
    queue = asyncio.Queue(maxsize=64)
    _subscribers.append(queue)
    return queue


def unsubscribe(queue):
    if queue in _subscribers:
        _subscribers.remove(queue)
