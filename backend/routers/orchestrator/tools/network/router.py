import anyio
from fastapi import APIRouter, HTTPException

from .tool import NETWORK_COMMANDS, command_label, execute_network_command

router = APIRouter(prefix="/linux/tools/network", tags=["tools"])

# Self-description picked up by the top-level tools catalog (GET /linux/tools/) — adding a new
# tool group means adding one entry to that catalog's list, not editing it in place.
TOOL_GROUP_INFO = {
    "name": "network",
    "description": (
        "Read-only diagnostics for connectivity, interfaces, wireless, routing, DNS, sockets and "
        "firewalls."
    ),
    "catalog_path": "/linux/tools/network/",
}


@router.get("/")
async def list_network_tools():
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
        for cid, entry in NETWORK_COMMANDS.items()
    ]


@router.get("/{command_id}")
async def run_network_tool(command_id: str, arg: str | None = None):
    """The parameter is `arg` as in the process group, because here it may be an interface name, a
    hostname or IP, or a port number."""
    if command_id not in NETWORK_COMMANDS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown command '{command_id}'. Valid: {', '.join(NETWORK_COMMANDS)}",
        )

    output = await anyio.to_thread.run_sync(execute_network_command, command_id, arg)
    return {"command": command_id, "label": command_label(command_id), "arg": arg, "output": output}
