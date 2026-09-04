from datetime import datetime

from pydantic import BaseModel


class SessionRecord(BaseModel):
    session_id: int
    session_name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ChatTurn(BaseModel):
    """One turn in a session's transcript, already parsed out of storage XML into the same shape the
    live orchestrator WebSocket's `final` event has - the frontend replays a session through the
    exact renderers it already uses for a live turn, never touching XML itself."""

    chat_id: int
    role: str
    created_at: datetime
    # "multi" here means several agents answered the turn: the reports are in `agents`, one entry per
    # agent, rather than in the single-report fields below.
    mode: str | None = None
    thinking: str | None = None
    content: str | None = None
    summary: str | None = None
    # Left as loose dicts, like the reports beside them - this model exists to carry the orchestrator's
    # own event shape to the frontend, not to re-validate it on the way out.
    agents: list = []
    disk_report: dict | None = None
    process_report: dict | None = None
    network_report: dict | None = None
    commands_run: list = []
