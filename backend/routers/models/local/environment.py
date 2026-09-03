"""Detects whether Ollama is installed and reachable. Opsy never installs it - we only detect and,
when it's missing or not running, say exactly what's missing and the command to fix it."""
import logging
import shutil

import httpx

logger = logging.getLogger("local-models")

OLLAMA_BASE_URL = "http://127.0.0.1:11434"
_CHECK_TIMEOUT = 3.0

# How every call to a local model is shaped. Defined here, once, because both the orchestrator's
# non-streaming client (classification, session titles, general chat) and the agents' streaming tool
# loop need exactly the same policy - and when the same number is spelled out in two modules, one of
# them eventually drifts.
#
# Set explicitly and generously rather than left at Ollama's small default: the standing rule is a
# bigger context window, never a smaller tool schema. A four-round tool loop against a full command
# schema plus accumulating command output needs the room.
LOCAL_CONTEXT_LENGTH = 16384

# A local model generating on CPU can take much longer than a hosted provider ever would, so the read
# timeout is generous - but the connect timeout stays short, so an unreachable Ollama still fails fast
# instead of hanging for ten minutes before reporting the real problem.
LOCAL_TIMEOUT = httpx.Timeout(connect=5.0, read=600.0, write=30.0, pool=5.0)


async def check_environment():
    if not shutil.which("ollama"):
        logger.info("local-models - ollama unavailable: not found on PATH")
        return {
            "available": False,
            "running": False,
            "version": None,
            "detail": "Ollama isn't installed. Install it from https://ollama.com/download, then reload this page.",
        }

    try:
        async with httpx.AsyncClient(timeout=_CHECK_TIMEOUT) as client:
            response = await client.get(f"{OLLAMA_BASE_URL}/api/version")
        response.raise_for_status()
        version = response.json().get("version")
        return {"available": True, "running": True, "version": version, "detail": None}
    except httpx.HTTPError as e:
        logger.info(f"local-models - ollama unavailable: nothing listening on 11434 ({e})")
        return {
            "available": True,
            "running": False,
            "version": None,
            "detail": "Ollama isn't running. Start it with `ollama serve`, then reload this page.",
        }
