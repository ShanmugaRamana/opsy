from fastapi import FastAPI

from routers import health, root, system

app = FastAPI(title="Opsy API")

app.include_router(root.router)
app.include_router(health.router)
app.include_router(system.router)
