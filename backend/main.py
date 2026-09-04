import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.db import get_connection
from routers import byok, hardware, health, models, onboarding, orchestrator, root, sessions, system, user
from routers.models.local.queries import clear_stale_downloads
from routers.models.local.router import router as local_models_router
from routers.orchestrator.agents.base.router import router as base_agent_router
from routers.orchestrator.agents.disk.router import router as disk_agent_router
from routers.orchestrator.agents.network.router import router as network_agent_router
from routers.orchestrator.agents.process.router import router as process_agent_router
from routers.orchestrator.agents.router import router as agents_catalog_router
from routers.orchestrator.memory.router import router as memory_catalog_router
from routers.orchestrator.memory.short_term.router import router as short_term_memory_router
from routers.orchestrator.tools.command.router import router as command_tools_router
from routers.orchestrator.tools.disk.router import router as disk_tools_router
from routers.orchestrator.tools.network.router import router as network_tools_router
from routers.orchestrator.tools.process.router import router as process_tools_router
from routers.orchestrator.supervisor.router import router as supervisor_router
from routers.orchestrator.tools.router import router as tools_catalog_router
from routers.orchestrator.tools.system.router import router as system_tools_router
from routers.user.preferences.router import router as user_preferences_router

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s - %(message)s")

app = FastAPI(title="Zyros API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(root.router)
app.include_router(health.router)
app.include_router(system.router)
app.include_router(onboarding.router)
app.include_router(user.router)
app.include_router(user_preferences_router)
app.include_router(hardware.router)
app.include_router(byok.router)
app.include_router(models.router)
app.include_router(local_models_router)
app.include_router(sessions.router)
app.include_router(orchestrator.router)

# The orchestrator's own supervisor (routers/orchestrator/supervisor/) — GET
# /linux/orchestrator/supervisor/ describes it; /plan decides which agents answer a message and
# /compose writes the paragraph over their reports. The orchestrator calls both over loopback.
app.include_router(supervisor_router)

# Category: agents (routers/orchestrator/agents/) — GET /linux/agents/ catalogs every agent; each
# agent's own router (e.g. /linux/agents/disk/ws) is mounted alongside it.
app.include_router(agents_catalog_router)
app.include_router(disk_agent_router)
app.include_router(process_agent_router)
app.include_router(network_agent_router)
app.include_router(base_agent_router)

# Category: tools (routers/orchestrator/tools/) — GET /linux/tools/ catalogs every tool group; each
# group's own router (e.g. /linux/tools/disk/{command_id}) is mounted alongside it.
app.include_router(tools_catalog_router)
app.include_router(disk_tools_router)
app.include_router(process_tools_router)
app.include_router(network_tools_router)
app.include_router(system_tools_router)
app.include_router(command_tools_router)

# Category: memory (routers/orchestrator/memory/) — GET /linux/memory/ catalogs every memory kind;
# each kind's own router (e.g. /linux/memory/short-term/{session_id}) is mounted alongside it.
app.include_router(memory_catalog_router)
app.include_router(short_term_memory_router)


@app.on_event("startup")
def _clear_stale_local_downloads():
    """A `downloading` row left over from a process that died mid-pull would otherwise look like a
    live progress bar that will never move - see local/queries.py:clear_stale_downloads.

    Connecting is inside the guard, not before it: an exception escaping a startup handler aborts the
    whole boot ("Application startup failed. Exiting."), and `get_connection()` raises when the
    database is unreachable. This cleanup is a nice-to-have, so a database that is briefly down must
    cost us this one housekeeping pass, not the entire backend - every route opens its own connection
    lazily and reports a 503 for itself."""
    try:
        conn = get_connection()
    except Exception:
        logging.getLogger("local-models").warning(
            "could not connect to check for stale downloads on startup", exc_info=True
        )
        return

    try:
        clear_stale_downloads(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        logging.getLogger("local-models").warning("could not check for stale downloads on startup", exc_info=True)
    finally:
        conn.close()
