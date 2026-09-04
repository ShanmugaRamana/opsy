from fastapi import APIRouter

from routers.orchestrator.agents.base.router import AGENT_INFO as _base_agent_info
from routers.orchestrator.agents.disk.router import AGENT_INFO as _disk_agent_info
from routers.orchestrator.agents.network.router import AGENT_INFO as _network_agent_info
from routers.orchestrator.agents.process.router import AGENT_INFO as _process_agent_info

router = APIRouter(prefix="/linux/agents", tags=["agents"])

# One entry per agent package under routers/agents/. Adding a new agent means adding its AGENT_INFO
# here, not editing any existing agent's code.
#
# The base agent (registered under the mode "general") is a peer of the three specialists, not a
# fallback path: it is what answers when none of them claims the question, over its own route, with
# its own tools and the same event contract.
AGENT_REGISTRY = [_disk_agent_info, _process_agent_info, _network_agent_info, _base_agent_info]

# mode (as returned by classify_intent) -> the agent's WebSocket path. Every mode the classifier can
# return is in here, so the orchestrator relays unconditionally rather than keeping a branch of its
# own for the ones that are not agents - there are none.
AGENT_WS_PATHS = {info["name"]: info["ws_path"] for info in AGENT_REGISTRY}


@router.get("/")
async def list_agents():
    """Every registered agent, so the category is browsable without reading the source."""
    return AGENT_REGISTRY
