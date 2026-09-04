from typing import Optional

from pydantic import BaseModel


class EnvironmentStatus(BaseModel):
    available: bool
    running: bool
    version: Optional[str] = None
    detail: Optional[str] = None


class CatalogEntry(BaseModel):
    model_key: str
    tag: str
    display_name: str
    category: str
    params_b: float
    quantization: str
    size_gb: float
    tool_calling: str
    streams_tool_calls: bool


class RecommendationEntry(BaseModel):
    model_key: str
    tag: str
    display_name: str
    category: str
    params_b: float
    quantization: str
    size_gb: float
    tool_calling: str
    streams_tool_calls: bool
    fit: str
    installed: bool = False


class ModelCategory(BaseModel):
    key: str
    label: str
    summary: str
    blurb: str
    usable_gb: float
    source: str


class RecommendationsResponse(BaseModel):
    environment: EnvironmentStatus
    # None only when we couldn't measure memory - in which case `models` is empty and `note` says so.
    category: Optional[ModelCategory] = None
    # Every entry here is downloadable: anything this machine can't run or hasn't the disk for was
    # excluded server-side rather than sent for the page to grey out.
    models: list[RecommendationEntry]
    note: Optional[str] = None


class CatalogCategory(BaseModel):
    key: str
    label: str
    summary: str
    min_usable_gb: float
    max_usable_gb: Optional[float] = None
    floor_gb: float
    models: list[CatalogEntry]


class CatalogResponse(BaseModel):
    backend: str
    max_params_b: float
    models_per_category: int
    categories: list[CatalogCategory]


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
