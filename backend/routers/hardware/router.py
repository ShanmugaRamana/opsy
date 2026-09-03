import logging

from fastapi import APIRouter

from . import collector, insights
from .schemas import HardwareProfile, InsightsResponse

logger = logging.getLogger("hardware")

router = APIRouter(prefix="/linux/hardware", tags=["hardware"])


@router.get("/profile", response_model=HardwareProfile)
def get_profile():
    profile = {
        "os": collector.get_os_name(),
        "cpu": {
            "model": collector.get_cpu_model(),
            "cores": collector.get_cpu_cores(),
            "usage_percent": collector.get_cpu_usage_percent(),
        },
        "ram": collector.get_ram() or {},
        "gpu": collector.get_gpu(),
        "storage": collector.get_storage() or {},
    }

    unavailable = [k for k in ("os", "gpu") if profile[k] is None]
    if profile["cpu"]["model"] is None:
        unavailable.append("cpu.model")
    logger.info(f"profile collected (unavailable={unavailable or 'none'})")

    return profile


@router.get("/profile/insights", response_model=InsightsResponse)
def get_insights():
    return {"insights": insights.build_insights()}
