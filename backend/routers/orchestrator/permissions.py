"""Pending approvals for commands the agent asks to run.

The event stream from an agent to the browser is one-way, so a decision cannot travel back along it.
Rather than thread a reply channel through two nested async generators and the loopback WebSocket,
the agent registers a request here, emits a `permission_request` event, and waits on a future. The
browser answers over a separate REST call, which settles that future.

The whole application is one process, so a module-level dict is the entire mechanism. Entries live
only for the turn that created them.
"""
import asyncio
import logging
import os
import uuid

logger = logging.getLogger("orchestrator.permissions")

# A request nobody answers must not hold a turn open forever - a closed tab would wedge it.
PERMISSION_TIMEOUT = float(os.getenv("COMMAND_PERMISSION_TIMEOUT", "300"))

_PENDING: dict[str, dict] = {}


def create(argv, reason):
    """Registers a request and returns its id. The argv is kept so that execution can be checked
    against exactly what the user saw and approved."""
    request_id = uuid.uuid4().hex
    _PENDING[request_id] = {
        "future": asyncio.get_running_loop().create_future(),
        "argv": [str(token) for token in argv],
        "reason": reason or "",
        "approved": False,
    }
    return request_id


def resolve(request_id, approved):
    """Settles a request from the browser. Returns "ok", "unknown" or "already_settled" so the route
    can answer with a real status instead of pretending every call worked."""
    entry = _PENDING.get(request_id)
    if entry is None:
        return "unknown"
    if entry["future"].done():
        return "already_settled"

    entry["approved"] = bool(approved)
    entry["future"].set_result(bool(approved))
    return "ok"


async def wait(request_id):
    """Blocks until the browser answers, or the timeout denies it on the user's behalf."""
    entry = _PENDING.get(request_id)
    if entry is None:
        return False

    try:
        return await asyncio.wait_for(entry["future"], PERMISSION_TIMEOUT)
    except asyncio.TimeoutError:
        entry["approved"] = False
        logger.warning(f"permission request {request_id} went unanswered for {PERMISSION_TIMEOUT}s, denying")
        return False


def approved_argv(request_id):
    """The argv this request was approved for, or None if it was denied or never existed.

    Execution is checked against this, so an approval cannot be reused for a different command on a
    later round."""
    entry = _PENDING.get(request_id)
    if entry is None or not entry["approved"]:
        return None
    return entry["argv"]


def discard(request_id):
    _PENDING.pop(request_id, None)
