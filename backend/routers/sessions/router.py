from fastapi import APIRouter, HTTPException

from core.db import get_connection
from routers.orchestrator.turn_state import get_running_turn
from routers.orchestrator.xml_output import from_storage_xml
from .queries import activate_session, get_session, list_chats, list_sessions
from .schemas import ChatTurn, SessionRecord

router = APIRouter(prefix="/linux/sessions", tags=["sessions"])


def _to_turn(row):
    if row["role"] == "user":
        return ChatTurn(chat_id=row["chat_id"], role="user", created_at=row["created_at"], content=row["chat"])

    parsed = from_storage_xml(row["chat"])
    return ChatTurn(
        chat_id=row["chat_id"],
        role="assistant",
        created_at=row["created_at"],
        mode=parsed.get("mode"),
        thinking=parsed.get("thinking"),
        content=parsed.get("content"),
        disk_report=parsed.get("disk_report"),
        process_report=parsed.get("process_report"),
        network_report=parsed.get("network_report"),
        commands_run=parsed.get("commands_run", []),
    )


@router.get("", response_model=list[SessionRecord])
def get_sessions():
    conn = get_connection()
    try:
        return list_sessions(conn)
    finally:
        conn.close()


@router.get("/{session_id}/chats", response_model=list[ChatTurn])
def get_session_chats(session_id: int):
    conn = get_connection()
    try:
        if get_session(conn, session_id) is None:
            raise HTTPException(status_code=404, detail="No such session")
        return [_to_turn(row) for row in list_chats(conn, session_id)]
    finally:
        conn.close()


@router.post("/{session_id}/activate", response_model=SessionRecord)
def activate(session_id: int):
    running = get_running_turn()
    if running is not None and running["session_id"] != session_id:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "A chat is already running.",
                "session_id": running["session_id"],
                "session_name": running["session_name"],
            },
        )

    conn = get_connection()
    try:
        session = get_session(conn, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="No such session")
        activate_session(conn, session_id)
        conn.commit()
        return get_session(conn, session_id)
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()
