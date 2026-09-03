"""The loopback client for the short-term memory route.

The direct counterpart of agents/shared.py:call_command_tool - the window is fetched over the real
HTTP route rather than by importing memory.py, so the boundary between the orchestrator and its
memory is a wire contract like every other boundary in this backend. It lives in the memory package
rather than in each caller because four callers share it.
"""
import logging
import os

import httpx

logger = logging.getLogger("orchestrator.memory")

INTERNAL_API_BASE = os.getenv("INTERNAL_API_BASE", "http://127.0.0.1:8000")

# Short: this is a single indexed read on the local database, sitting in front of a turn the user is
# already waiting on. If it cannot answer in this long, the turn is better off without it.
MEMORY_TIMEOUT = 10.0


async def fetch_short_term(session_id):
    """The session's memory window, as neutral [{"role", "content"}] turns.

    Never raises. Memory improves a turn, it is not a precondition for one, so an unreachable route,
    a timeout, or a session that has since been deleted degrades this turn to the stateless
    behaviour Opsy had before memory existed - a warning in the log and an empty window, rather than
    a chat that fails outright because a helper was down.
    """
    try:
        async with httpx.AsyncClient(timeout=MEMORY_TIMEOUT) as client:
            response = await client.get(f"{INTERNAL_API_BASE}/linux/memory/short-term/{session_id}")
        if response.status_code == 404:
            logger.warning(f"short-term memory: session {session_id} not found, continuing without history")
            return []
        response.raise_for_status()
        return response.json().get("turns", [])
    except (httpx.HTTPError, ValueError, KeyError) as e:
        logger.warning(f"short-term memory unavailable, continuing without history: {e}")
        return []
