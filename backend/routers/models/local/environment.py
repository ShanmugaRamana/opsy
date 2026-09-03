"""Detects whether Ollama is installed and reachable. Opsy never installs it - we only detect and,
when it's missing or not running, say exactly what's missing and the command to fix it."""
import logging
import shutil

import httpx

logger = logging.getLogger("local-models")

OLLAMA_BASE_URL = "http://127.0.0.1:11434"
_CHECK_TIMEOUT = 3.0


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
