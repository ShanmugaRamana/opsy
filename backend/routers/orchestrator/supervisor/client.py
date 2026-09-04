"""The loopback client for the supervisor's routes.

The direct counterpart of memory/short_term/client.py and agents/shared.py:call_command_tool - the
plan and the composed paragraph are fetched over the real HTTP routes rather than by importing
plan.py and compose.py, so the boundary between the orchestrator and its supervisor is a wire
contract like every other boundary in this backend.

The two functions fail in deliberately opposite ways, because what they produce is worth different
things to a turn:

- `plan_turn` raises ProviderCallError, exactly as the classifier call it replaced did. Without a
  plan there is no agent to run, so the turn genuinely cannot continue, and core.py's existing
  handler already turns that exception into the right 429/502 error event.
- `compose_summary` returns None. The reports it summarises are already in hand by the time it runs,
  so its failure costs a paragraph, never an answer.
"""
import logging
import os

import httpx

from routers.orchestrator.clients import ProviderCallError

logger = logging.getLogger("orchestrator.supervisor")

INTERNAL_API_BASE = os.getenv("INTERNAL_API_BASE", "http://127.0.0.1:8000")

# This wraps a provider call that may itself wait out a rate limit, and against a local model may
# generate for minutes (see local/environment.py:LOCAL_TIMEOUT). The read timeout therefore has to
# outlast the innermost call - a shorter one here would fire first and report a loopback timeout for
# what is really a slow model, hiding the actual cause. The connect timeout stays short, so a backend
# that is not listening still fails immediately.
_LOOPBACK_TIMEOUT = httpx.Timeout(connect=5.0, read=660.0, write=30.0, pool=5.0)

_BASE_PATH = "/linux/orchestrator/supervisor"


def _detail(response):
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    detail = body.get("detail") if isinstance(body, dict) else None
    return detail if isinstance(detail, str) else str(detail or response.text[:300])


async def plan_turn(provider, api_key, model_id, message, base_url=None, history=None):
    """The agents that should answer this message, as a list of {"mode", "question"} steps.

    Raises ProviderCallError on any failure, including an unreachable route: a turn with no plan has
    nothing to run, and reporting that as a provider failure puts it on the one path core.py already
    knows how to end a turn with."""
    payload = {
        "provider": provider,
        "api_key": api_key,
        "model_id": model_id,
        "message": message,
        "base_url": base_url,
        "history": history or [],
    }

    try:
        async with httpx.AsyncClient(timeout=_LOOPBACK_TIMEOUT) as client:
            response = await client.post(f"{INTERNAL_API_BASE}{_BASE_PATH}/plan", json=payload)
        if response.status_code >= 400:
            raise ProviderCallError(_detail(response), rate_limited=response.status_code == 429)
        return response.json()["steps"]
    except (httpx.HTTPError, KeyError, ValueError) as e:
        raise ProviderCallError(f"supervisor plan route unreachable: {e}") from e


async def compose_summary(provider, api_key, model_id, message, results, base_url=None):
    """The paragraph tying several agents' findings together, or None.

    Never raises. The route itself already answers a failed composition with a null summary; this
    also swallows the route being unreachable, so a supervisor that is down costs the paragraph and
    nothing else."""
    payload = {
        "provider": provider,
        "api_key": api_key,
        "model_id": model_id,
        "message": message,
        "base_url": base_url,
        "results": results or [],
    }

    try:
        async with httpx.AsyncClient(timeout=_LOOPBACK_TIMEOUT) as client:
            response = await client.post(f"{INTERNAL_API_BASE}{_BASE_PATH}/compose", json=payload)
        response.raise_for_status()
        return response.json().get("summary")
    except (httpx.HTTPError, ValueError) as e:
        logger.warning(f"supervisor compose route unavailable, answering without a summary: {e}")
        return None
