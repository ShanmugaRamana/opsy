import anyio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from routers.orchestrator import permissions

from .tool import DEFAULT_TIMEOUT, DENIED_BINARIES, execute_command

router = APIRouter(prefix="/linux/tools/command", tags=["tools"])

# Self-description picked up by the top-level tools catalog (GET /linux/tools/).
TOOL_GROUP_INFO = {
    "name": "command",
    "description": "Runs a read-only command the user explicitly approved, for questions the fixed allow-lists do not cover.",
    "catalog_path": "/linux/tools/command/",
}


class RunApprovedCommand(BaseModel):
    request_id: str = Field(min_length=1)
    argv: list[str] = Field(min_length=1)
    timeout: int = DEFAULT_TIMEOUT
    count_lines: bool = False


@router.get("/")
async def describe_command_tool():
    """Unlike the disk group there is no fixed command list here, so the catalogue entry describes
    the rules instead: what cannot be run, and that nothing runs without approval."""
    return {
        **TOOL_GROUP_INFO,
        "requires_approval": True,
        "shell": False,
        "denied_binaries": sorted(DENIED_BINARIES),
    }


@router.post("/run")
async def run_approved_command(payload: RunApprovedCommand):
    """Runs a command the user approved. The approval is bound to the exact argv it was granted for,
    so an approval cannot be reused for a different command on a later round."""
    approved = permissions.approved_argv(payload.request_id)
    if approved is None:
        raise HTTPException(status_code=403, detail="This command was not approved by the user.")

    if approved != list(payload.argv):
        raise HTTPException(
            status_code=403,
            detail="This command does not match the one the user approved.",
        )

    output = await anyio.to_thread.run_sync(
        execute_command, list(payload.argv), payload.timeout, payload.count_lines
    )
    return {"argv": list(payload.argv), "output": output}
