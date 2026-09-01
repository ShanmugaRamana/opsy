from fastapi import APIRouter, HTTPException

from core.db import get_connection
from .queries import insert_user, user_table_has_rows
from .schemas import OnboardingUserPayload

router = APIRouter(prefix="/linux/onboarding", tags=["onboarding"])


@router.get("/verify")
def verify_onboarding():
    conn = get_connection()
    try:
        has_rows = user_table_has_rows(conn)
        return {"onboarding_required": not has_rows}
    finally:
        conn.close()


@router.post("/user")
def create_onboarding_user(payload: OnboardingUserPayload):
    conn = get_connection()
    try:
        insert_user(conn, payload.name, payload.linux_experience, payload.role_use_case)
        conn.commit()
        return {"message": "success"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()
