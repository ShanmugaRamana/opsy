from typing import Optional

from pydantic import BaseModel


class EnvironmentStatus(BaseModel):
    available: bool
    running: bool
    version: Optional[str] = None
    detail: Optional[str] = None


class RecommendationEntry(BaseModel):
    model_key: str
    tag: str
    display_name: str
    params_b: float
    quantization: str
    size_gb: float
    tool_calling: str
    fit: str
    reason: Optional[str] = None
    installed: bool = False


class RecommendationsResponse(BaseModel):
    environment: EnvironmentStatus
    recommendations: list[RecommendationEntry]


class LocalModelRecord(BaseModel):
    model_key: str
    model_ref: str
    display_name: str
    params_b: Optional[float] = None
    quantization: Optional[str] = None
    size_bytes: Optional[int] = None
    status: str
    error: Optional[str] = None
    downloaded_at: Optional[str] = None


class DownloadStartRequest(BaseModel):
    model_key: str


class DownloadStartResponse(BaseModel):
    model_key: str
    model_ref: str
    display_name: str
