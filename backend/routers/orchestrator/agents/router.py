from fastapi import APIRouter

from routers.orchestrator.agents.disk.router import AGENT_INFO as _disk_agent_info
from routers.orchestrator.agents.network.router import AGENT_INFO as _network_agent_info
from routers.orchestrator.agents.process.router import AGENT_INFO as _process_agent_info

router = APIRouter(prefix="/linux/agents", tags=["agents"])

# One entry per agent package under routers/agents/. Adding a new agent means adding its AGENT_INFO
# here, not editing any existing agent's code.
AGENT_REGISTRY = [_disk_agent_info, _process_agent_info, _network_agent_info]

# mode (as returned by classify_intent) -> the agent's WebSocket path. The orchestrator routes off
# this rather than an if/elif chain, so a third agent is a registry entry and nothing else.
AGENT_WS_PATHS = {info["name"]: info["ws_path"] for info in AGENT_REGISTRY}


@router.get("/")
async def list_agents():
    """Every registered agent, so the category is browsable without reading the source."""
    return AGENT_REGISTRY
