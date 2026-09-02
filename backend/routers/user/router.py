from fastapi import APIRouter

from core.db import get_connection
from .queries import list_users
from .schemas import UserRecord

router = APIRouter(prefix="/linux", tags=["user"])


@router.get("/users", response_model=list[UserRecord])
def list_all_users():
    conn = get_connection()
    try:
        return list_users(conn)
    finally:
        conn.close()
