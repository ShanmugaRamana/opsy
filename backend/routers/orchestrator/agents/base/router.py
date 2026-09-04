import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError

from routers.orchestrator.memory.short_term.schemas import HistoryTurn

from .tool_clients import run_base_agent

logger = logging.getLogger("orchestrator.base")

router = APIRouter(prefix="/linux/agents/base", tags=["agents"])

# Self-description picked up by the top-level agents catalog (GET /linux/agents/) — adding a new
# agent means adding one entry to that catalog's list, not editing it in place.
#
# The name is the mode the classifier returns, which is what the orchestrator routes on, so this
# agent registers as "general" while its package is "base": "general" is both a real classification
# and the classifier's no-match fallback, and renaming it would mean rewriting the classifier prompt
# for no change in behaviour.
AGENT_INFO = {
    "name": "general",
    "description": (
        "Answers everything the specialist agents don't claim, reading this machine's hardware "
        "profile and asking to run read-only commands when the answer depends on what is actually "
        "there."
    ),
    "ws_path": "/linux/agents/base/ws",
}


class BaseAgentRequest(BaseModel):
    provider: str
    # None for local providers (e.g. Ollama), which need no key - base_url carries where to reach
    # them instead.
    api_key: Optional[str] = None
    model_id: str
    message: str = Field(min_length=1)
    base_url: Optional[str] = None
    # The session's memory window, resolved by the orchestrator and passed down the same way api_key
    # and base_url are. Defaulted so this route stays directly callable without memory.
    history: list[HistoryTurn] = []


@router.get("/")
async def get_base_agent():
    """This agent's own record — the single-item view of its entry in the GET /linux/agents/
    catalog, mirroring how GET /linux/agents/disk/ is the single view of the disk agent's."""
    return AGENT_INFO


@router.websocket("/ws")
async def base_agent_ws(websocket: WebSocket):
    """Runs the base agent for exactly one request, streaming its events, then closes. Only ever
    called by the orchestrator itself (via /linux/orchestrator/ws) — not a multi-turn connection
    like that one."""
    await websocket.accept()
    try:
        payload = await websocket.receive_json()
        try:
            request = BaseAgentRequest(**payload)
        except ValidationError as e:
            await websocket.send_json({"type": "error", "detail": str(e)})
            return

        async for event in run_base_agent(
            request.provider, request.api_key, request.model_id, request.message,
            base_url=request.base_url, history=request.history,
        ):
            await websocket.send_json(event)
    except WebSocketDisconnect:
        logger.info("base agent ws client disconnected")
    finally:
        try:
            await websocket.close()
        except RuntimeError:
            pass
