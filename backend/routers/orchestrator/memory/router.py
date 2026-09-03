from fastapi import APIRouter

from routers.orchestrator.memory.short_term.router import MEMORY_INFO as _short_term_memory_info

router = APIRouter(prefix="/linux/memory", tags=["memory"])

# One entry per memory kind under routers/orchestrator/memory/. Adding a second kind (long-term
# machine facts, rolling summaries of turns that fell out of the short-term window) means adding its
# MEMORY_INFO here, not editing any existing kind's code.
MEMORY_REGISTRY = [_short_term_memory_info]


@router.get("/")
async def list_memory_kinds():
    """Every registered memory kind, so the category is browsable without reading the source."""
    return MEMORY_REGISTRY
