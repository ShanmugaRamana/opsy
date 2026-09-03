import anyio
from fastapi import APIRouter, HTTPException

from .tool import DISK_COMMANDS, command_label, execute_disk_command

router = APIRouter(prefix="/linux/tools/disk", tags=["tools", "disk"])


@router.get("/{command_id}")
async def run_disk_tool(command_id: str):
    if command_id not in DISK_COMMANDS:
        valid = ", ".join(DISK_COMMANDS)
        raise HTTPException(status_code=404, detail=f"Unknown command '{command_id}'. Valid: {valid}")

    output = await anyio.to_thread.run_sync(execute_disk_command, command_id)
    return {"command": command_id, "label": command_label(command_id), "output": output}
