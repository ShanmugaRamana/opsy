import anyio
from fastapi import APIRouter, HTTPException

from .tool import SYSTEM_COMMANDS, command_label, execute_system_command

router = APIRouter(prefix="/linux/tools/system", tags=["tools"])

# Self-description picked up by the top-level tools catalog (GET /linux/tools/) — adding a new
# tool group means adding one entry to that catalog's list, not editing it in place.
TOOL_GROUP_INFO = {
    "name": "system",
    "description": "Read-only commands about what this machine is: OS, kernel, uptime, time, locale, "
                   "session, and which programs and packages are installed.",
    "catalog_path": "/linux/tools/system/",
}


@router.get("/")
async def list_system_tools():
    """The full allow-list, so the catalogue is inspectable without reading the source."""
    return [
        {
            "command": cid,
            "label": entry.label,
            "description": entry.description,
            "name": entry.name_mode,
        }
        for cid, entry in SYSTEM_COMMANDS.items()
    ]


@router.get("/{command_id}")
async def run_system_tool(command_id: str, name: str | None = None):
    if command_id not in SYSTEM_COMMANDS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown command '{command_id}'. Valid: {', '.join(SYSTEM_COMMANDS)}",
        )

    output = await anyio.to_thread.run_sync(execute_system_command, command_id, name)
    return {"command": command_id, "label": command_label(command_id), "name": name, "output": output}
