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
from routers.sessions.queries import (
    create_session,
    delete_trailing_user_chats,
    get_session,
    insert_chat,
    rename_session,
    touch_session,
)

from .agents.router import AGENT_WS_PATHS
from .clients import ProviderCallError, call_provider
from .memory.short_term.client import fetch_short_term
from .prompts import SESSION_TITLE_SYSTEM_PROMPT
from .schemas import OrchestratorRequest
from .supervisor.client import compose_summary, plan_turn
from .turn_state import clear_running_turn, get_running_turn, set_running_turn
from .xml_output import to_storage_xml

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


def _drop_unanswered_user_chats_sync(session_id, chat_text):
    conn = get_connection()
    try:
        removed = delete_trailing_user_chats(conn, session_id, chat_text)
        conn.commit()
        return removed
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


async def _relay_agent(mode, provider, api_key, model_id, message, base_url=None, history=None):
    """Calls a specialist agent over its real WS route (loopback) rather than importing and calling
    it directly, relaying every event it streams back unchanged.

    A socket that closes mid-turn would otherwise end the relay silently, leaving the client with a
    collapsed trace and no answer, so a close without a terminal event becomes an error.

    The memory window is resolved here and handed over in the payload rather than being fetched again
    by the agent, following what already happens with `api_key` and `base_url`: the orchestrator
    resolves what a turn needs and passes the resolved values down. The agent still defaults it to an
    empty list, so its route stays directly callable without memory."""
    ws_path = AGENT_WS_PATHS.get(mode)
    if ws_path is None:
        # Every mode the classifier can return is registered, so this means the classifier prompt and
        # the registry have drifted apart. Since the orchestrator no longer keeps a path of its own to
        # fall back to, that drift ends the turn with a real error rather than a KeyError that would
        # take the socket down with it.
        logger.error(f"no agent registered for mode {mode!r}")
        yield {"type": "error", "status": 500, "detail": f"no agent is registered for '{mode}'"}
        return

    saw_terminal = False
    try:
        async with websockets.connect(f"{INTERNAL_WS_BASE}{ws_path}") as ws:
            await ws.send(json.dumps({
                "provider": provider,
                "api_key": api_key,
                "model_id": model_id,
                "message": message,
                "base_url": base_url,
                "history": history or [],
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


def _agent_message(step, message):
    """What one agent is actually sent.

    A single-agent turn, and any agent the planner gave no sub-question, gets the user's message
    unchanged - which is what every turn did before this existed. A sub-question is sent with the
    original message attached rather than in place of it: the focus keeps two agents off each other's
    half of a compound question, and the original keeps the words the user actually typed in front of
    the agent that has to answer them."""
    question = (step.get("question") or "").strip()
    if not question:
        return message
    return f'{question}\n\nThe user\'s full message was: "{message}"'


async def _fan_out(steps, provider, api_key, model_id, message, base_url=None, history=None):
    """Runs two or three agents in sequence and folds them into one composite `final`.

    Sequential on purpose. Two agents at once would interleave their `thinking_delta` into a single
    trace panel, race two permission prompts at the user simultaneously, and double the rate of
    provider calls that ratelimit.space_calls() exists to space out.

    Each agent's own terminal event is captured rather than forwarded - it is that agent's result,
    not the turn's - and re-emitted as `agent_final`/`agent_error` so the client can close out that
    agent's section while the turn continues. One agent failing is therefore not the turn failing,
    which is the right rule the moment there is more than one; only a turn where every agent failed
    ends in a terminal error.
    """
    total = len(steps)
    results = []

    for index, step in enumerate(steps):
        mode = step["mode"]
        yield {"type": "agent_started", "mode": mode, "index": index, "total": total}

        slot = None
        async for event in _relay_agent(
            mode, provider, api_key, model_id, _agent_message(step, message),
            base_url=base_url, history=history,
        ):
            kind = event.get("type")
            if kind == "final":
                slot = {key: value for key, value in event.items() if key != "type"}
                slot["mode"] = mode
                yield {"type": "agent_final", **slot}
                continue
            if kind == "error":
                slot = {"mode": mode, "error": event.get("detail") or "this agent failed"}
                yield {"type": "agent_error", **slot}
                continue
            # Stamped with the agent that produced it. Tool events already carry `agent`, but a
            # thinking_delta does not, and with several agents in one turn the client has to know
            # whose reasoning it is watching.
            yield {**event, "mode": mode}

        if slot is None:
            # _relay_agent guarantees a terminal event, so this is unreachable unless that contract
            # breaks. Recorded as a failed slot anyway: a missing result must not become a silently
            # shorter answer.
            logger.error(f"{mode} agent relay produced no terminal event")
            slot = {"mode": mode, "error": "this agent returned no result"}
            yield {"type": "agent_error", **slot}

        results.append(slot)

    failed = [slot for slot in results if slot.get("error")]
    if len(failed) == len(results):
        detail = "; ".join(f"{slot['mode']}: {slot['error']}" for slot in failed)
        yield {"type": "error", "status": 502, "detail": f"every agent failed - {detail}"}
        return

    # Best-effort by contract: a failure here returns None and the turn renders and stores the
    # reports it already has, exactly as the session-title call above never costs a turn.
    summary = await compose_summary(provider, api_key, model_id, message, results, base_url=base_url)

    yield {
        "type": "final",
        "mode": "multi",
        "modes": [slot["mode"] for slot in results],
        "summary": summary,
        "agents": results,
        # Flattened in the order the agents ran, so anything reading this field sees every command
        # the turn ran without having to know a turn can now have several agents.
        "commands_run": [
            command for slot in results for command in (slot.get("commands_run") or [])
        ],
    }


async def _run_turn(steps, provider, api_key, model_id, message, base_url=None, history=None):
    """The turn's agent phase, ending in exactly one terminal event either way.

    One planned agent is relayed exactly as it always has been: its own events, its own terminal
    event, nothing added and nothing renamed. The multi path only exists from two agents up, so a
    single-subject question is byte-for-byte the turn it was before fan-out existed."""
    if len(steps) == 1:
        async for event in _relay_agent(
            steps[0]["mode"], provider, api_key, model_id, _agent_message(steps[0], message),
            base_url=base_url, history=history,
        ):
            yield event
        return

    async for event in _fan_out(
        steps, provider, api_key, model_id, message, base_url=base_url, history=history
    ):
        yield event


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

    # Read the session's memory before logging this message, so the turn being answered is not part
    # of its own context. (The memory route drops an unanswered user row anyway, so the window would
    # be the same either way - this ordering just makes the intent explicit.) A brand new session has
    # nothing to remember and skips the call entirely.
    history = [] if is_new_session else await fetch_short_term(session_id)

    # A retry re-sends a message whose turn already failed, and that attempt left a user row with no
    # reply behind it. Clearing those first keeps one row per question no matter how many times it is
    # retried - otherwise the replayed transcript would show the same message once per attempt, and
    # the short-term window would over-fetch to step past all of them.
    if request.is_retry and not is_new_session:
        removed = await anyio.to_thread.run_sync(
            _drop_unanswered_user_chats_sync, session_id, request.message
        )
        if removed:
            logger.info(f"retry: dropped {removed} unanswered user row(s) from session {session_id}")

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
                # planner's first token arrives - this keeps the UI honest about what's happening
                # instead of leaving the user staring at a dead spinner. Purely additive: it only ever
                # appears before "classified", and a client that ignores it sees the same sequence as
                # any cloud turn.
                yield {"type": "model_loading", "model_id": request.model_id}

            steps = None
            try:
                steps = await plan_turn(
                    request.provider, api_key, request.model_id, request.message,
                    base_url=base_url, history=history,
                )
            except ProviderCallError as e:
                logger.error(f"planning failed: {e}")
                yield {
                    "type": "error",
                    "status": 429 if getattr(e, "rate_limited", False) else 502,
                    "detail": f"planning failed: {e}",
                }

            if steps:
                # `mode` is kept alongside `modes` so a client that predates fan-out still gets a
                # usable header from the first agent rather than nothing at all.
                modes = [step["mode"] for step in steps]
                yield {"type": "classified", "mode": modes[0], "modes": modes}

                # Every mode the planner can return is an agent with a route, including "general"
                # (the base agent), so there is no branch here for answering a question in-process -
                # the orchestrator plans, relays and persists, and nothing else. Persisting stays
                # here, on the one terminal event, whether that came from a single agent or from the
                # composite the fan-out built.
                async for event in _run_turn(
                    steps, request.provider, api_key, request.model_id, request.message,
                    base_url=base_url, history=history,
                ):
                    if event["type"] == "error":
                        event.setdefault("status", 502)
                    if event["type"] == "final":
                        event["session_id"] = session_id
                        await _persist_final(session_id, event)
                    yield event
    finally:
        clear_running_turn()

    title = title_holder.get("title") if is_new_session else None
    if title:
        await anyio.to_thread.run_sync(_rename_session_sync, session_id, title)
        yield {"type": "session_renamed", "session_id": session_id, "session_name": title}
