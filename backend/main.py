import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import byok, hardware, health, models, onboarding, orchestrator, root, sessions, system, user
from routers.orchestrator.agents.disk.router import router as disk_agent_router
from routers.orchestrator.agents.process.router import router as process_agent_router
from routers.orchestrator.agents.router import router as agents_catalog_router
from routers.orchestrator.tools.command.router import router as command_tools_router
from routers.orchestrator.tools.disk.router import router as disk_tools_router
from routers.orchestrator.tools.process.router import router as process_tools_router
from routers.orchestrator.tools.router import router as tools_catalog_router

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s - %(message)s")

app = FastAPI(title="Opsy API")

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
app.include_router(hardware.router)
app.include_router(byok.router)
app.include_router(models.router)
app.include_router(sessions.router)
app.include_router(orchestrator.router)

# Category: agents (routers/orchestrator/agents/) — GET /linux/agents/ catalogs every agent; each
# agent's own router (e.g. /linux/agents/disk/ws) is mounted alongside it.
app.include_router(agents_catalog_router)
app.include_router(disk_agent_router)
app.include_router(process_agent_router)

# Category: tools (routers/orchestrator/tools/) — GET /linux/tools/ catalogs every tool group; each
# group's own router (e.g. /linux/tools/disk/{command_id}) is mounted alongside it.
app.include_router(tools_catalog_router)
app.include_router(disk_tools_router)
app.include_router(process_tools_router)
app.include_router(command_tools_router)
