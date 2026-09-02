from fastapi import APIRouter, HTTPException

from core.db import get_connection
from routers.byok.queries import has_any_key
from .queries import insert_user, user_table_has_rows
from .schemas import OnboardingUserPayload

router = APIRouter(prefix="/linux/onboarding", tags=["onboarding"])


@router.get("/verify")
def verify_onboarding():
    conn = get_connection()
    try:
        has_rows = user_table_has_rows(conn)
        onboarding_required = not has_rows

        setup_required = False if onboarding_required else not has_any_key(conn)

        return {
            "onboarding_required": onboarding_required,
            "setup_required": setup_required,
        }
    finally:
        conn.close()


@router.post("/user")
def create_onboarding_user(payload: OnboardingUserPayload):
    conn = get_connection()
    try:
        insert_user(conn, payload.name, payload.profile_pic, payload.linux_experience, payload.role_use_case)
        conn.commit()
        return {"message": "success"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()
