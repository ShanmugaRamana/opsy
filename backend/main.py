from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import health, onboarding, root, system, user

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
