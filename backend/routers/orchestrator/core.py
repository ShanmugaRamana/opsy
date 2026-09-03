import json
import logging
import os

import anyio
import websockets
from fastapi import HTTPException

from core.crypto import decrypt
from core.db import get_connection
from routers.byok.queries import get_key
from routers.models.local.runtime import LocalProviderUnavailable, resolve_endpoint
from routers.models.providers import ALL_PROVIDERS, is_local
from routers.sessions.queries import create_session, get_session, insert_chat, rename_session, touch_session

from .agents.router import AGENT_WS_PATHS
from .classify import classify_intent
from .clients import ProviderCallError, call_provider
from .prompts import BASE_SYSTEM_PROMPT, SESSION_TITLE_SYSTEM_PROMPT
from .schemas import OrchestratorRequest
from .turn_state import clear_running_turn, get_running_turn, set_running_turn
from .xml_output import parse_response, to_storage_xml

logger = logging.getLogger("orchestrator")

INTERNAL_WS_BASE = os.getenv("INTERNAL_WS_BASE", "ws://127.0.0.1:8000")

NEW_SESSION_PLACEHOLDER_NAME = "New chat"


def _get_key_sync(provider):
    conn = get_connection()
    try:
        return get_key(conn, provider)
    finally:
        conn.close()


def _create_session_sync(name):
    conn = get_connection()
    try:
        session_id = create_session(conn, name)
        conn.commit()
        return session_id
    finally:
        conn.close()


def _get_session_name_sync(session_id):
    conn = get_connection()
    try:
        session = get_session(conn, session_id)
        return session["session_name"] if session else None
    finally:
        conn.close()


def _insert_chat_sync(session_id, role, chat_text):
    conn = get_connection()
    try:
        insert_chat(conn, session_id, role, chat_text)
        conn.commit()
    finally:
        conn.close()


def _touch_session_sync(session_id):
    conn = get_connection()
    try:
        touch_session(conn, session_id)
        conn.commit()
    finally:
        conn.close()


def _rename_session_sync(session_id, name):
    conn = get_connection()
    try:
        rename_session(conn, session_id, name)
        conn.commit()
    finally:
        conn.close()


async def _persist_final(session_id, final_event):
    chat_xml = to_storage_xml(final_event)
    await anyio.to_thread.run_sync(_insert_chat_sync, session_id, "assistant", chat_xml)
    await anyio.to_thread.run_sync(_touch_session_sync, session_id)


async def _generate_title(provider, api_key, model_id, message, base_url=None):
    """Best-effort short title for a new session, from the same provider/model the user picked.
    Any failure just leaves the session named "New chat" rather than blocking the turn on it - this
    runs alongside the main turn in the same task group, so a raised exception here must not be
    allowed to cancel that turn."""
    try:
        raw = await call_provider(
            provider, api_key, model_id, SESSION_TITLE_SYSTEM_PROMPT, message, base_url=base_url
        )
    except Exception as e:
        logger.warning(f"session title generation failed: {e}")
        return None

    title = (raw or "").strip().strip('"').strip("'")
    title = title.splitlines()[0].strip() if title else ""
    return title[:80] or None


async def _relay_agent(mode, provider, api_key, model_id, message, base_url=None):
    """Calls a specialist agent over its real WS route (loopback) rather than importing and calling
    it directly, relaying every event it streams back unchanged.

    A socket that closes mid-turn would otherwise end the relay silently, leaving the client with a
    collapsed trace and no answer, so a close without a terminal event becomes an error."""
    ws_path = AGENT_WS_PATHS[mode]
    saw_terminal = False
    try:
        async with websockets.connect(f"{INTERNAL_WS_BASE}{ws_path}") as ws:
            await ws.send(json.dumps({
                "provider": provider,
                "api_key": api_key,
                "model_id": model_id,
                "message": message,
                "base_url": base_url,
            }))
            async for raw in ws:
                event = json.loads(raw)
                if event.get("type") in ("final", "error"):
                    saw_terminal = True
                yield event
    except (OSError, websockets.exceptions.WebSocketException) as e:
        logger.error(f"{mode} agent route unreachable: {e}")
        if not saw_terminal:
            yield {"type": "error", "status": 502, "detail": f"{mode} agent unreachable: {e}"}
        return

    if not saw_terminal:
        logger.error(f"{mode} agent socket closed without a terminal event")
        yield {
            "type": "error",
            "status": 502,
            "detail": f"{mode} agent closed without returning a result",
        }


async def run_orchestrator(request: OrchestratorRequest):
    """Async generator: yields event dicts as the turn progresses. The last event is always
    type "final" (success), "error" (failure), or "already_running" (rejected before anything
    started). Shared by both the WS endpoint (forwards every event live) and the POST endpoint
    (drains to the final event).

    Every turn gets logged to the sessions/chats tables: a fresh chat (session_id is None) creates
    and activates a new session first; an existing session_id just appends to it. Only one turn may
    be in flight system-wide at a time - see turn_state - so starting a brand new chat while another
    is still running is rejected outright rather than silently queued.
    """
    running = get_running_turn()
    if request.session_id is None and running is not None:
        yield {"type": "already_running", "session_id": running["session_id"], "session_name": running["session_name"]}
        return

    if request.provider not in ALL_PROVIDERS:
        yield {"type": "error", "status": 400, "detail": f"Unknown provider: {request.provider}"}
        return

    base_url = None
    if is_local(request.provider):
        try:
            base_url, api_key = await resolve_endpoint(request.provider, request.model_id)
        except LocalProviderUnavailable as e:
            yield {"type": "error", "status": 503, "detail": str(e)}
            return
    else:
        try:
            key_row = await anyio.to_thread.run_sync(_get_key_sync, request.provider)
        except HTTPException as e:
            yield {"type": "error", "status": e.status_code, "detail": e.detail}
            return

        if key_row is None:
            yield {"type": "error", "status": 404, "detail": f"No stored API key for provider: {request.provider}"}
            return

        api_key = decrypt(key_row["api_key_encrypted"])

    is_new_session = request.session_id is None
    if is_new_session:
        session_id = await anyio.to_thread.run_sync(_create_session_sync, NEW_SESSION_PLACEHOLDER_NAME)
        session_name = NEW_SESSION_PLACEHOLDER_NAME
        yield {"type": "session_created", "session_id": session_id, "session_name": session_name}
    else:
        session_id = request.session_id
        session_name = await anyio.to_thread.run_sync(_get_session_name_sync, session_id)

    await anyio.to_thread.run_sync(_insert_chat_sync, session_id, "user", request.message)

    # No early `return` from here on, deliberately: every exit needs to fall through to the
    # `finally` (clear the running-turn tracker) and then the title follow-up below, regardless of
    # which branch the turn took or whether it succeeded - a `return` inside the `try` would skip
    # both by exiting the generator outright.
    set_running_turn(session_id, session_name)
    try:
        async with anyio.create_task_group() as tg:
            title_holder = {}
            if is_new_session:
                async def _title_worker():
                    title_holder["title"] = await _generate_title(
                        request.provider, api_key, request.model_id, request.message, base_url=base_url
                    )
                tg.start_soon(_title_worker)

            yield {"type": "started"}

            if is_local(request.provider):
                # A local model not already resident can take tens of seconds to load before the
                # classifier's first token arrives - this keeps the UI honest about what's happening
                # instead of leaving the user staring at a dead spinner. Purely additive: it only ever
                # appears before "classified", and a client that ignores it sees the same sequence as
                # any cloud turn.
                yield {"type": "model_loading", "model_id": request.model_id}

            mode = None
            try:
                mode = await classify_intent(
                    request.provider, api_key, request.model_id, request.message, base_url=base_url
                )
            except ProviderCallError as e:
                logger.error(f"classification failed: {e}")
                yield {
                    "type": "error",
                    "status": 429 if getattr(e, "rate_limited", False) else 502,
                    "detail": f"classification failed: {e}",
                }

            if mode is not None:
                yield {"type": "classified", "mode": mode}

                if mode in AGENT_WS_PATHS:
                    async for event in _relay_agent(
                        mode, request.provider, api_key, request.model_id, request.message, base_url=base_url
                    ):
                        if event["type"] == "error":
                            event.setdefault("status", 502)
                        if event["type"] == "final":
                            event["session_id"] = session_id
                            await _persist_final(session_id, event)
                        yield event
                else:
                    try:
                        raw_text = await call_provider(
                            request.provider, api_key, request.model_id, BASE_SYSTEM_PROMPT, request.message,
                            base_url=base_url,
                        )
                    except ProviderCallError as e:
                        logger.error(f"{request.provider} call failed: {e}")
                        yield {
                            "type": "error",
                            "status": 429 if getattr(e, "rate_limited", False) else 502,
                            "detail": f"{request.provider} call failed: {e}",
                        }
                    else:
                        thinking, content = parse_response(raw_text)
                        final_event = {
                            "type": "final",
                            "mode": "general",
                            "session_id": session_id,
                            "thinking": thinking,
                            "content": content,
                            "raw_xml": raw_text,
                        }
                        await _persist_final(session_id, final_event)
                        yield final_event
    finally:
        clear_running_turn()

    title = title_holder.get("title") if is_new_session else None
    if title:
        await anyio.to_thread.run_sync(_rename_session_sync, session_id, title)
        yield {"type": "session_renamed", "session_id": session_id, "session_name": title}
