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
    mode: str | None = None
    thinking: str | None = None
    content: str | None = None
    disk_report: dict | None = None
    process_report: dict | None = None
    commands_run: list = []
