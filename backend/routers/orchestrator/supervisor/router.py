import logging

from fastapi import APIRouter, HTTPException

from routers.orchestrator.clients import ProviderCallError

from .compose import MAX_SUMMARY_CHARS, compose_summary
from .plan import AGENT_MODES, GENERAL, MAX_STEPS, plan_turn
from .schemas import ComposeRequest, ComposeResponse, PlanRequest, PlanResponse

logger = logging.getLogger("orchestrator.supervisor")

router = APIRouter(prefix="/linux/orchestrator/supervisor", tags=["supervisor"])

# Self-description in the same shape the agents and tool groups publish, so this subsystem is
# browsable with curl rather than only by reading the source.
SUPERVISOR_INFO = {
    "name": "supervisor",
    "description": (
        "Plans which agents answer a message - one to three, in the order they should run - and "
        "composes their finished reports into a single combined answer."
    ),
    "catalog_path": "/linux/orchestrator/supervisor/",
}


@router.get("/")
async def describe_supervisor():
    """This subsystem's own record, plus the policy it applies. The agent cap and the exclusivity
    rule are answerable over HTTP rather than only by reading plan.py."""
    return {
        **SUPERVISOR_INFO,
        "routes": {
            "POST /linux/orchestrator/supervisor/plan": "which agents should answer a message",
            "POST /linux/orchestrator/supervisor/compose": "one paragraph over several agents' reports",
        },
        "agents": [*AGENT_MODES, GENERAL],
        "max_agents_per_turn": MAX_STEPS,
        "fallback": GENERAL,
        "exclusive": f"'{GENERAL}' is dropped whenever a specialist is also named",
        "max_summary_chars": MAX_SUMMARY_CHARS,
        "compose": "best-effort - a failure returns a null summary, never an error",
    }


@router.post("/plan", response_model=PlanResponse)
async def post_plan(request: PlanRequest):
    """The agents that should answer this message.

    A provider failure surfaces as a real status - 429 for a rate limit, 502 otherwise - so the
    orchestrator's loopback client can turn it back into the same ProviderCallError its caller has
    always handled."""
    try:
        steps = await plan_turn(
            request.provider, request.api_key, request.model_id, request.message,
            base_url=request.base_url, history=request.history,
        )
    except ProviderCallError as e:
        raise HTTPException(status_code=429 if e.rate_limited else 502, detail=str(e))

    return {"steps": steps}


@router.post("/compose", response_model=ComposeResponse)
async def post_compose(request: ComposeRequest):
    """The combined paragraph over several agents' results.

    Deliberately never an error status: this route composes from findings the caller already has, so
    the honest failure is "no paragraph", not "your turn failed"."""
    summary = await compose_summary(
        request.provider, request.api_key, request.model_id, request.message, request.results,
        base_url=request.base_url,
    )
    return {"summary": summary}
