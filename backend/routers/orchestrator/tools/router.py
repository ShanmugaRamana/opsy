from fastapi import APIRouter

from routers.orchestrator.tools.command.router import TOOL_GROUP_INFO as _command_tool_group_info
from routers.orchestrator.tools.disk.router import TOOL_GROUP_INFO as _disk_tool_group_info

router = APIRouter(prefix="/linux/tools", tags=["tools"])

# One entry per tool group under routers/tools/. Adding a new tool group means adding its
# TOOL_GROUP_INFO here, not editing any existing tool group's code.
TOOL_GROUP_REGISTRY = [_disk_tool_group_info, _command_tool_group_info]


@router.get("/")
async def list_tool_groups():
    """Every registered tool group, so the category is browsable without reading the source."""
    return TOOL_GROUP_REGISTRY
