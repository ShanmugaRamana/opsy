import asyncio
import logging

import httpx
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from core.db import get_connection
from routers.hardware import collector

from . import download_state
from .catalog import BACKEND, get_entry
from .download import run_download
from .environment import OLLAMA_BASE_URL, check_environment
from .queries import STATUS_READY, delete_model, list_local_models
from .recommend import build_recommendations
from .schemas import (
    DownloadStartRequest,
    DownloadStartResponse,
    EnvironmentStatus,
    LocalModelRecord,
    RecommendationsResponse,
)

logger = logging.getLogger("local-models")

router = APIRouter(prefix="/linux/local-models", tags=["local-models"])

# Kept referenced so asyncio doesn't garbage-collect the running pull mid-transfer. The task's actual
# lifecycle - progress, completion, cancellation - is tracked in download_state, not here.
_download_task = None


@router.get("/environment", response_model=EnvironmentStatus)
async def get_environment():
    return await check_environment()


@router.get("/recommendations", response_model=RecommendationsResponse)
async def get_recommendations():
    env = await check_environment()

    profile = {
        "gpu": collector.get_gpu(),
        "ram": collector.get_ram(),
        "storage": collector.get_storage(),
    }
    recommendations = build_recommendations(profile)

    conn = get_connection()
    try:
        installed = {row["model_key"] for row in list_local_models(conn) if row["status"] == STATUS_READY}
    finally:
        conn.close()

    for entry in recommendations:
        entry["installed"] = entry["model_key"] in installed

    return {"environment": env, "recommendations": recommendations}


@router.get("/", response_model=list[LocalModelRecord])
def list_installed():
    conn = get_connection()
    try:
        rows = list_local_models(conn)
    finally:
        conn.close()

    return [
        {
            "model_key": r["model_key"],
            "model_ref": r["model_ref"],
            "display_name": r["display_name"],
            "params_b": float(r["params_b"]) if r["params_b"] is not None else None,
            "quantization": r["quantization"],
            "size_bytes": r["size_bytes"],
            "status": r["status"],
            "error": r["error"],
            "downloaded_at": str(r["downloaded_at"]) if r["downloaded_at"] else None,
        }
        for r in rows
    ]


@router.post("/download", response_model=DownloadStartResponse, status_code=202)
async def start_download_route(payload: DownloadStartRequest):
    global _download_task

    entry = get_entry(payload.model_key)
    if entry is None:
        raise HTTPException(status_code=400, detail=f"Unknown model: {payload.model_key}")

    if download_state.is_running():
        active = download_state.get_snapshot()
        raise HTTPException(
            status_code=409,
            detail=f"A download is already running: {active['display_name']}",
        )

    env = await check_environment()
    if not env["running"]:
        raise HTTPException(status_code=503, detail=env["detail"] or "Ollama is not reachable")

    logger.info(f"local-models - starting download: {payload.model_key}")
    _download_task = asyncio.create_task(run_download(payload.model_key))

    return {"model_key": payload.model_key, "model_ref": entry["tag"], "display_name": entry["display_name"]}


@router.post("/download/cancel")
def cancel_download_route():
    if not download_state.is_running():
        raise HTTPException(status_code=404, detail="No download in progress.")
    download_state.request_cancel()
    return {"cancelled": True}


@router.websocket("/download/ws")
async def download_ws(websocket: WebSocket):
    """A viewer, not the download's owner - see download_state.py. Sends the current snapshot
    immediately so a page opened mid-pull renders at the right percent instead of starting at zero,
    then relays live events until a terminal one arrives."""
    await websocket.accept()

    snapshot = download_state.get_snapshot()
    if snapshot is None:
        await websocket.send_json({"type": "error", "detail": "No download in progress."})
        await websocket.close()
        return

    await websocket.send_json({"type": "snapshot", **snapshot})

    if snapshot["status"] != download_state.STATUS_DOWNLOADING:
        await websocket.close()
        return

    queue = download_state.subscribe()
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
            if event["type"] in ("done", "error"):
                break
    except WebSocketDisconnect:
        logger.info("local-models - download viewer disconnected")
    finally:
        download_state.unsubscribe(queue)
        try:
            await websocket.close()
        except RuntimeError:
            pass


@router.delete("/{model_key}")
async def delete_local_model_route(model_key: str):
    entry = get_entry(model_key)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown model: {model_key}")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.request("DELETE", f"{OLLAMA_BASE_URL}/api/delete", json={"model": entry["tag"]})
    except httpx.HTTPError as e:
        logger.warning(f"local-models - ollama rm for {entry['tag']} failed (removing our record anyway): {e}")

    conn = get_connection()
    try:
        delete_model(conn, model_key)
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

    return {"deleted": model_key, "provider": BACKEND}
