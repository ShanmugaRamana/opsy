from typing import Optional

from pydantic import BaseModel


class CPUInfo(BaseModel):
    model: Optional[str] = None
    cores: Optional[int] = None
    usage_percent: Optional[float] = None


class RAMInfo(BaseModel):
    total_gb: Optional[float] = None
    used_gb: Optional[float] = None


class GPUInfo(BaseModel):
    model: Optional[str] = None
    dedicated: Optional[bool] = None
    usage_percent: Optional[float] = None
    vram_gb: Optional[float] = None


class StorageInfo(BaseModel):
    total_gb: Optional[float] = None
    free_gb: Optional[float] = None


class HardwareProfile(BaseModel):
    os: Optional[str] = None
    cpu: CPUInfo
    ram: RAMInfo
    gpu: Optional[GPUInfo] = None
    storage: StorageInfo


class Insight(BaseModel):
    id: str
    title: str
    detail: str
    severity: str


class InsightsResponse(BaseModel):
    insights: list[Insight]
