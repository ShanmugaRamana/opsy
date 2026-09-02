import logging

from fastapi import APIRouter, HTTPException

from core.crypto import encrypt
from core.db import get_connection
from . import providers
from .queries import list_keys, upsert_key
from .schemas import ApiKeyPayload, ApiKeyVerifyResult, ConfiguredProvider, VALID_PROVIDERS

logger = logging.getLogger("byok")

router = APIRouter(prefix="/linux/byok", tags=["byok"])


@router.post("/key", response_model=ApiKeyVerifyResult)
def verify_and_store_key(payload: ApiKeyPayload):
    if payload.provider not in VALID_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {payload.provider}")

    result = providers.verify_key(payload.provider, payload.api_key)

    if result == "invalid":
        raise HTTPException(status_code=401, detail="Invalid API key")
    if result == "unreachable":
        raise HTTPException(status_code=503, detail="Could not reach provider")

    encrypted = encrypt(payload.api_key)
    last4 = payload.api_key[-4:]

    conn = get_connection()
    try:
        upsert_key(conn, payload.provider, encrypted, last4)
        conn.commit()
        logger.info(f"stored encrypted key for {payload.provider}")
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

    return {"valid": True, "provider": payload.provider}


@router.get("/keys", response_model=list[ConfiguredProvider])
def list_configured_keys():
    conn = get_connection()
    try:
        rows = list_keys(conn)
        return [
            {
                "provider": r["provider"],
                "key_last4": r["key_last4"],
                "verified_at": str(r["verified_at"]),
            }
            for r in rows
        ]
    finally:
        conn.close()
