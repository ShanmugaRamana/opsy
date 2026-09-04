import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from . import permissions
from .core import run_orchestrator
from .schemas import OrchestratorRequest, OrchestratorResponse

logger = logging.getLogger("orchestrator")

router = APIRouter(prefix="/linux/orchestrator", tags=["orchestrator"])


class PermissionDecision(BaseModel):
    decision: str


@router.post("/permissions/{request_id}")
async def decide_permission(request_id: str, payload: PermissionDecision):
    """Answers a command the agent asked to run.

    The decision arrives here rather than on the WebSocket because the event stream is one-way; the
    agent is waiting on a future that this settles."""
    decision = payload.decision.strip().lower()
    if decision not in ("approve", "deny"):
        raise HTTPException(status_code=400, detail="decision must be 'approve' or 'deny'")

    outcome = permissions.resolve(request_id, decision == "approve")
    if outcome == "unknown":
        raise HTTPException(status_code=404, detail="No such permission request, or it already expired.")
    if outcome == "already_settled":
        raise HTTPException(status_code=409, detail="That permission request was already answered.")

    return {"request_id": request_id, "decision": decision}


@router.post("/run", response_model=OrchestratorResponse)
async def run(payload: OrchestratorRequest):
    final_event = None

    async for event in run_orchestrator(payload):
        if event["type"] == "error":
            raise HTTPException(status_code=event.get("status", 502), detail=event["detail"])
        if event["type"] == "already_running":
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "A chat is already running.",
                    "session_id": event["session_id"],
                    "session_name": event["session_name"],
                },
            )
        if event["type"] == "final":
            final_event = event

    if final_event is None:
        raise HTTPException(status_code=502, detail="orchestrator produced no result")

    mode = final_event["mode"]
    return OrchestratorResponse(
        provider=payload.provider,
        model_id=payload.model_id,
        session_id=final_event.get("session_id"),
        mode=mode,
        # A single-agent turn has no `modes` of its own, so one is written from its mode here rather
        # than leaving this empty - a caller reading `modes` should never have to fall back to `mode`.
        modes=final_event.get("modes") or [mode],
        summary=final_event.get("summary"),
        agents=final_event.get("agents", []),
        thinking=final_event.get("thinking"),
        content=final_event.get("content"),
        raw_xml=final_event.get("raw_xml"),
        disk_report=final_event.get("disk_report"),
        process_report=final_event.get("process_report"),
        network_report=final_event.get("network_report"),
        commands_run=final_event.get("commands_run", []),
    )


@router.websocket("/ws")
async def orchestrator_ws(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            payload = await websocket.receive_json()
            try:
                request = OrchestratorRequest(**payload)
            except ValidationError as e:
                await websocket.send_json({"type": "error", "detail": str(e)})
                continue

            async for event in run_orchestrator(request):
                await websocket.send_json(event)
    except WebSocketDisconnect:
        logger.info("orchestrator ws client disconnected")
