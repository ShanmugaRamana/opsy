import anyio
from fastapi import APIRouter, HTTPException

from .tool import DISK_COMMANDS, command_label, execute_disk_command

router = APIRouter(prefix="/linux/tools/disk", tags=["tools"])

# Self-description picked up by the top-level tools catalog (GET /linux/tools/) — adding a new
# tool group means adding one entry to that catalog's list, not editing it in place.
TOOL_GROUP_INFO = {
    "name": "disk",
    "description": "Read-only disk and storage diagnostic commands.",
    "catalog_path": "/linux/tools/disk/",
}


@router.get("/")
async def list_disk_tools():
    """The full allow-list, so the catalogue is inspectable without reading the source."""
    return [
        {
            "command": cid,
            "label": entry.label,
            "description": entry.description,
            "path": entry.path_mode,
            "needs_root": entry.needs_root,
        }
        for cid, entry in DISK_COMMANDS.items()
    ]


@router.get("/{command_id}")
async def run_disk_tool(command_id: str, path: str | None = None):
    if command_id not in DISK_COMMANDS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown command '{command_id}'. Valid: {', '.join(DISK_COMMANDS)}",
        )

    output = await anyio.to_thread.run_sync(execute_disk_command, command_id, path)
    return {"command": command_id, "label": command_label(command_id), "path": path, "output": output}
