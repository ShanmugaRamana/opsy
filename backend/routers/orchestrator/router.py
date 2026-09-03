import logging

from fastapi import APIRouter, HTTPException

from core.crypto import decrypt
from core.db import get_connection
from routers.byok.queries import get_key
from routers.byok.schemas import VALID_PROVIDERS
from .clients import ProviderCallError, call_provider
from .prompts import BASE_SYSTEM_PROMPT
from .schemas import OrchestratorRequest, OrchestratorResponse
from .xml_output import parse_response

logger = logging.getLogger("orchestrator")

router = APIRouter(prefix="/linux/orchestrator", tags=["orchestrator"])


@router.post("/run", response_model=OrchestratorResponse)
def run(payload: OrchestratorRequest):
    if payload.provider not in VALID_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {payload.provider}")

    conn = get_connection()
    try:
        key_row = get_key(conn, payload.provider)
    finally:
        conn.close()

    if key_row is None:
        raise HTTPException(status_code=404, detail=f"No stored API key for provider: {payload.provider}")

    api_key = decrypt(key_row["api_key_encrypted"])

    try:
        raw_text = call_provider(payload.provider, api_key, payload.model_id, BASE_SYSTEM_PROMPT, payload.message)
    except ProviderCallError as e:
        logger.error(f"{payload.provider} call failed: {e}")
        raise HTTPException(status_code=502, detail=f"{payload.provider} call failed: {e}")

    thinking, content = parse_response(raw_text)

    return {
        "provider": payload.provider,
        "model_id": payload.model_id,
        "thinking": thinking,
        "content": content,
        "raw_xml": raw_text,
    }
