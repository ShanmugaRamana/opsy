import json
import logging
import os

import anyio
import websockets
from fastapi import HTTPException

from core.crypto import decrypt
from core.db import get_connection
from routers.byok.queries import get_key
from routers.byok.schemas import VALID_PROVIDERS

from .classify import classify_intent
from .clients import ProviderCallError, call_provider
from .prompts import BASE_SYSTEM_PROMPT
from .schemas import OrchestratorRequest
from .xml_output import parse_response

logger = logging.getLogger("orchestrator")

INTERNAL_WS_BASE = os.getenv("INTERNAL_WS_BASE", "ws://127.0.0.1:8000")


def _get_key_sync(provider):
    conn = get_connection()
    try:
        return get_key(conn, provider)
    finally:
        conn.close()


async def _relay_disk_agent(provider, api_key, model_id, message):
    """Calls the disk agent over its real WS route (loopback) rather than importing and calling it
    directly, relaying every event it streams back unchanged."""
    try:
        async with websockets.connect(f"{INTERNAL_WS_BASE}/linux/agents/disk/ws") as ws:
            await ws.send(json.dumps({
                "provider": provider,
                "api_key": api_key,
                "model_id": model_id,
                "message": message,
            }))
            async for raw in ws:
                yield json.loads(raw)
    except (OSError, websockets.exceptions.WebSocketException) as e:
        logger.error(f"disk agent route unreachable: {e}")
        yield {"type": "error", "status": 502, "detail": f"disk agent unreachable: {e}"}


async def run_orchestrator(request: OrchestratorRequest):
    """Async generator: yields event dicts as the turn progresses. The last event is always
    type "final" (success) or "error" (failure). Shared by both the WS endpoint (forwards every
    event live) and the POST endpoint (drains to the final event)."""
    if request.provider not in VALID_PROVIDERS:
        yield {"type": "error", "status": 400, "detail": f"Unknown provider: {request.provider}"}
        return

    try:
        key_row = await anyio.to_thread.run_sync(_get_key_sync, request.provider)
    except HTTPException as e:
        yield {"type": "error", "status": e.status_code, "detail": e.detail}
        return

    if key_row is None:
        yield {"type": "error", "status": 404, "detail": f"No stored API key for provider: {request.provider}"}
        return

    api_key = decrypt(key_row["api_key_encrypted"])

    yield {"type": "started"}

    try:
        mode = await classify_intent(request.provider, api_key, request.model_id, request.message)
    except ProviderCallError as e:
        logger.error(f"classification failed: {e}")
        yield {"type": "error", "status": 502, "detail": f"classification failed: {e}"}
        return

    yield {"type": "classified", "mode": mode}

    if mode == "disk":
        async for event in _relay_disk_agent(request.provider, api_key, request.model_id, request.message):
            if event["type"] == "error":
                event.setdefault("status", 502)
            yield event
        return

    try:
        raw_text = await call_provider(
            request.provider, api_key, request.model_id, BASE_SYSTEM_PROMPT, request.message
        )
    except ProviderCallError as e:
        logger.error(f"{request.provider} call failed: {e}")
        yield {"type": "error", "status": 502, "detail": f"{request.provider} call failed: {e}"}
        return

    thinking, content = parse_response(raw_text)
    yield {
        "type": "final",
        "mode": "general",
        "thinking": thinking,
        "content": content,
        "raw_xml": raw_text,
    }
