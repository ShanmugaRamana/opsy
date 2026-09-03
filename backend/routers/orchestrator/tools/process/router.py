import anyio
from fastapi import APIRouter, HTTPException

from .tool import PROCESS_COMMANDS, command_label, execute_process_command

router = APIRouter(prefix="/linux/tools/process", tags=["tools"])

# Self-description picked up by the top-level tools catalog (GET /linux/tools/) — adding a new
# tool group means adding one entry to that catalog's list, not editing it in place.
TOOL_GROUP_INFO = {
    "name": "process",
    "description": "Read-only diagnostics for running applications, processes, load and services.",
    "catalog_path": "/linux/tools/process/",
}


@router.get("/")
async def list_process_tools():
    """The full allow-list, so the catalogue is inspectable without reading the source."""
    return [
        {
            "command": cid,
            "label": entry.label,
            "description": entry.description,
            "arg": entry.arg_mode,
            "arg_kind": entry.arg_kind if entry.arg_mode != "none" else None,
            "needs_root": entry.needs_root,
        }
        for cid, entry in PROCESS_COMMANDS.items()
    ]


@router.get("/{command_id}")
async def run_process_tool(command_id: str, arg: str | None = None):
    """The parameter is `arg` rather than the disk group's `path`, because here it may be a PID, a
    program name or a systemd unit as well as a directory."""
    if command_id not in PROCESS_COMMANDS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown command '{command_id}'. Valid: {', '.join(PROCESS_COMMANDS)}",
        )

    output = await anyio.to_thread.run_sync(execute_process_command, command_id, arg)
    return {"command": command_id, "label": command_label(command_id), "arg": arg, "output": output}
