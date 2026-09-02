from fastapi import APIRouter

from core.db import get_connection
from .queries import list_models
from .schemas import ModelRecord

router = APIRouter(prefix="/linux", tags=["models"])


@router.get("/models", response_model=list[ModelRecord])
def get_models(provider: str = None):
    conn = get_connection()
    try:
        return list_models(conn, provider)
    finally:
        conn.close()
