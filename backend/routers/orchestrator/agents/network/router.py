import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError

from .tool_clients import run_network_agent

logger = logging.getLogger("orchestrator.network")

router = APIRouter(prefix="/linux/agents/network", tags=["agents"])

# Self-description picked up by the top-level agents catalog (GET /linux/agents/) — adding a new
# agent means adding one entry to that catalog's list, not editing it in place.
AGENT_INFO = {
    "name": "network",
    "description": (
        "Answers questions about connectivity, wireless, routing, DNS, bandwidth, ports and what is "
        "using the network by running read-only diagnostic commands."
    ),
    "ws_path": "/linux/agents/network/ws",
}


class NetworkAgentRequest(BaseModel):
    provider: str
    api_key: str = Field(min_length=1)
    model_id: str
    message: str = Field(min_length=1)


@router.get("/")
async def get_network_agent():
    """This agent's own record — the single-item view of its entry in the GET /linux/agents/
    catalog, mirroring how GET /linux/tools/network/ is the single-group view under /linux/tools/."""
    return AGENT_INFO


@router.websocket("/ws")
async def network_agent_ws(websocket: WebSocket):
    """Runs the network agent for exactly one request, streaming its events, then closes. Only ever
    called by the orchestrator itself (via /linux/orchestrator/ws) — not a multi-turn connection
    like that one."""
    await websocket.accept()
    try:
        payload = await websocket.receive_json()
        try:
            request = NetworkAgentRequest(**payload)
        except ValidationError as e:
            await websocket.send_json({"type": "error", "detail": str(e)})
            return

        async for event in run_network_agent(
            request.provider, request.api_key, request.model_id, request.message
        ):
            await websocket.send_json(event)
    except WebSocketDisconnect:
        logger.info("network agent ws client disconnected")
    finally:
        try:
            await websocket.close()
        except RuntimeError:
            pass
