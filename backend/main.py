import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import byok, hardware, health, models, onboarding, orchestrator, root, system, user
from routers.orchestrator.agents.disk.router import router as disk_agent_router
from routers.tools.disk import router as disk_tools_router

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
app.include_router(orchestrator.router)
app.include_router(disk_tools_router)
app.include_router(disk_agent_router)
