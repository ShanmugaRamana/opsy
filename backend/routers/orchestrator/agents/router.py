from fastapi import APIRouter

from routers.orchestrator.agents.disk.router import AGENT_INFO as _disk_agent_info

router = APIRouter(prefix="/linux/agents", tags=["agents"])

# One entry per agent package under routers/agents/. Adding a new agent means adding its AGENT_INFO
# here, not editing any existing agent's code.
AGENT_REGISTRY = [_disk_agent_info]


@router.get("/")
async def list_agents():
    """Every registered agent, so the category is browsable without reading the source."""
    return AGENT_REGISTRY
