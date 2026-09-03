"""Resolves the endpoint a local provider's calls should go to. Ollama needs no API key - the second
element of the returned tuple exists purely so callers can hand it to the same `call_provider(...,
api_key, ...)` signature every cloud provider already uses, unchanged."""
import logging

import httpx

from .environment import OLLAMA_BASE_URL

logger = logging.getLogger("local-models")

_REACHABILITY_TIMEOUT = 3.0


class LocalProviderUnavailable(Exception):
    """Raised when a local provider can't be reached - surfaced to the client as a 503-shaped error
    event, not the 404 'no stored key' error a cloud provider gets, since the failure here has
    nothing to do with credentials."""


async def resolve_endpoint(provider, model_id):
    if provider != "ollama":
        raise LocalProviderUnavailable(f"unknown local provider: {provider}")

    try:
        async with httpx.AsyncClient(timeout=_REACHABILITY_TIMEOUT) as client:
            response = await client.get(f"{OLLAMA_BASE_URL}/api/version")
        response.raise_for_status()
    except httpx.HTTPError as e:
        logger.error(f"local-models - ollama unreachable: {e}")
        raise LocalProviderUnavailable("Ollama isn't running — start it with `ollama serve`.") from e

    return OLLAMA_BASE_URL, None
