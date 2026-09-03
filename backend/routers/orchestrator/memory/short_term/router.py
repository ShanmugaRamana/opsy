import anyio
from fastapi import APIRouter, HTTPException

from core.db import get_connection
from routers.sessions.queries import get_session

from . import render
from .memory import (
    FETCH_ROWS,
    MAX_CLASSIFIER_CHARS,
    MAX_HISTORY_CHARS,
    MAX_HISTORY_TURNS,
    build_window,
    load_rows,
)
from .schemas import ShortTermWindow

router = APIRouter(prefix="/linux/memory/short-term", tags=["memory"])

# Self-description picked up by the top-level memory catalog (GET /linux/memory/) - adding a new
# memory kind means adding one entry to that catalog's list, not editing it in place.
MEMORY_INFO = {
    "name": "short-term",
    "description": "The last 3 completed turns of a session, as conversation context for the next one.",
    "catalog_path": "/linux/memory/short-term/",
}

# One rendering per provider wire format, plus the classifier's inline form. Named by provider rather
# than by format so the inspection route can be called with the same provider string the rest of the
# system uses.
_RENDERERS = {
    "anthropic": render.as_anthropic,
    "openai": render.as_openai,
    "groq": render.as_openai,
    "ollama": render.as_openai,
    "gemini": render.as_gemini,
    "classifier": render.as_classifier_context,
}


def _session_exists_sync(session_id):
    conn = get_connection()
    try:
        return get_session(conn, session_id) is not None
    finally:
        conn.close()


async def _window(session_id):
    if not await anyio.to_thread.run_sync(_session_exists_sync, session_id):
        raise HTTPException(status_code=404, detail="No such session")

    rows = await anyio.to_thread.run_sync(load_rows, session_id)
    return build_window(session_id, rows)


@router.get("/")
async def describe_short_term_memory():
    """This memory kind's own record, plus the policy it applies - the single-item view of its entry
    in the GET /linux/memory/ catalog, mirroring how GET /linux/tools/disk/ lists that group's
    allow-list. The window size and caps are answerable over HTTP rather than only by reading the
    source."""
    return {
        **MEMORY_INFO,
        "max_turns": MAX_HISTORY_TURNS,
        "max_chars_per_message": MAX_HISTORY_CHARS,
        "max_chars_per_message_classifier": MAX_CLASSIFIER_CHARS,
        "rows_fetched": FETCH_ROWS,
        "turn": "one user message and the assistant reply it received",
        "skips": "turns that errored before they were answered, and rows that no longer parse",
        "excludes": "commands_run, which is trace data for the UI rather than conversation",
    }


@router.get("/{session_id}", response_model=ShortTermWindow)
async def get_short_term_memory(session_id: int):
    """The window the orchestrator threads into the next turn's provider call."""
    return await _window(session_id)


@router.get("/{session_id}/rendered")
async def get_rendered_short_term_memory(session_id: int, provider: str = "anthropic"):
    """The same window in one provider's own dialect.

    Nothing consumes this - the orchestrator renders at the point of the call, where the payload is
    being built anyway. It exists so "what exactly did Gemini see?" is answerable with curl, which is
    the reason every part of this backend is reachable over a route."""
    renderer = _RENDERERS.get(provider)
    if renderer is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown provider '{provider}'. Valid: {', '.join(_RENDERERS)}",
        )

    window = await _window(session_id)
    return {"session_id": session_id, "provider": provider, "rendered": renderer(window["turns"])}
