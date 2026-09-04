from pydantic import BaseModel, Field

from routers.orchestrator.memory.short_term.schemas import HistoryTurn


class PlanStep(BaseModel):
    """One agent to run, and what to ask it.

    `question` is advisory. When it is null the agent is sent the user's own message unchanged, which
    is what a single-agent turn always does; when it is set, the agent is sent that focused question
    with the original message attached as context, so a specialist on a compound question does not
    re-investigate the half another agent already owns."""

    mode: str
    question: str | None = None


class PlanRequest(BaseModel):
    provider: str
    # None for local providers (e.g. Ollama), which need no key - base_url carries where to reach
    # them instead. Sending it over loopback is what `_relay_agent` already does with every agent.
    api_key: str | None = None
    model_id: str
    message: str = Field(min_length=1)
    base_url: str | None = None
    # The session's memory window, resolved by the orchestrator and passed down the same way api_key
    # and base_url are. Defaulted so this route stays directly callable without memory.
    history: list[HistoryTurn] = []


class PlanResponse(BaseModel):
    # Always 1-3 entries, never empty: a reply naming nothing known falls back to a single "general"
    # step rather than an empty plan a caller would have to have its own fallback for.
    steps: list[PlanStep]


class ComposeRequest(BaseModel):
    provider: str
    api_key: str | None = None
    model_id: str
    message: str = Field(min_length=1)
    base_url: str | None = None
    # Each agent's `final` event minus its type, or {"mode", "error"} for one that failed. Left as
    # loose dicts on purpose: this is the agents' own output travelling back in, and a stricter model
    # here would silently drop a field the day an agent's report grows one.
    results: list[dict] = []


class ComposeResponse(BaseModel):
    # None whenever the paragraph could not be written - an unreachable provider, a rate limit, an
    # empty reply. The caller renders the reports without it rather than failing the turn.
    summary: str | None = None
