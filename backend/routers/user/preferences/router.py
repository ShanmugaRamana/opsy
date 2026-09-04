import logging

from fastapi import APIRouter, HTTPException

from core.db import get_connection
from .queries import get_preferences, set_always_approve_commands
from .schemas import PreferencesRecord, PreferencesUpdate

logger = logging.getLogger("user.preferences")

router = APIRouter(prefix="/linux/users", tags=["preferences"])

NO_USER_DETAIL = "No user has been onboarded yet."


@router.get("/preferences", response_model=PreferencesRecord)
def read_preferences():
    """The onboarded user's preferences.

    This is a real route rather than a helper because the orchestrator reads it over loopback when
    it decides whether to ask before running a command - see agents/shared.py:always_approve_commands.
    """
    conn = get_connection()
    try:
        row = get_preferences(conn)
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail=NO_USER_DETAIL)

    return {"always_approve_commands": row["always_approve_commands"]}


@router.put("/preferences", response_model=PreferencesRecord)
def update_preferences(payload: PreferencesUpdate):
    conn = get_connection()
    try:
        row = set_always_approve_commands(conn, payload.always_approve_commands)
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail=NO_USER_DETAIL)

    logger.info(f"always_approve_commands set to {row['always_approve_commands']}")
    return {"always_approve_commands": row["always_approve_commands"]}
