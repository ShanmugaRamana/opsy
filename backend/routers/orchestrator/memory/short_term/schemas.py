from pydantic import BaseModel


class HistoryTurn(BaseModel):
    """One message of prior conversation, in the provider-neutral form.

    `role` is only ever "user" or "assistant" - Gemini's rename of the assistant role to "model"
    happens in that provider's renderer (render.py), not on the wire, so nothing outside render.py
    has to know which provider the window is destined for.
    """

    role: str
    content: str


class ShortTermWindow(BaseModel):
    session_id: int
    turns: list[HistoryTurn] = []
    # Completed user+assistant pairs represented in `turns`, i.e. len(turns) // 2. Carried explicitly
    # so a caller can tell "this session is new" from "this session's history could not be read".
    turn_count: int = 0
    # True when any message was cut to the per-message character cap.
    truncated: bool = False
