from pydantic import BaseModel, Field


class OrchestratorRequest(BaseModel):
    provider: str
    model_id: str
    message: str = Field(min_length=1)


class CommandRun(BaseModel):
    command: str
    label: str
    path: str | None = None
    output: str


class TopConsumer(BaseModel):
    label: str
    size_gb: float | None = None


class Fact(BaseModel):
    label: str
    value: str


class Capacity(BaseModel):
    free_gb: float | None = None
    total_gb: float | None = None
    percent_used: float | None = None
    severity: str | None = None


class DiskReport(BaseModel):
    summary: str
    explanation: str | None = None
    capacity: Capacity | None = None
    facts: list[Fact] = []
    top_consumers: list[TopConsumer] = []
    suggestion: str | None = None
    # True when the model did not return a usable <disk_report> and the summary is prose recovered
    # from whatever it did say. The client keeps the trace expanded for these, since the commands
    # that ran are then more trustworthy than the answer.
    salvaged: bool = False


class AppEntry(BaseModel):
    """One application, not one process. A browser's renderer, GPU and crashpad processes are summed
    into a single entry, which is what makes "which apps are running" answerable."""

    name: str
    cpu_percent: float | None = None
    memory_mb: float | None = None
    processes: int | None = None
    uptime: str | None = None
    # foreground | background | unknown. "unknown" is required, not optional, whenever window data
    # was unavailable - claiming "background" on a Wayland session would be inventing an observation.
    state: str | None = None
    detail: str | None = None


class ProcessEntry(BaseModel):
    pid: int | None = None
    name: str
    cpu_percent: float | None = None
    memory_mb: float | None = None
    state: str | None = None


class LoadSummary(BaseModel):
    cpu_percent: float | None = None
    memory_percent: float | None = None
    load_1m: float | None = None
    cores: int | None = None
    severity: str | None = None


class ProcessReport(BaseModel):
    summary: str
    explanation: str | None = None
    # full | degraded. Mirrors what the tool reported about this session's window data, so the client
    # can state the limitation instead of quietly rendering a weaker answer as a confident one.
    confidence: str | None = None
    apps: list[AppEntry] = []
    processes: list[ProcessEntry] = []
    load: LoadSummary | None = None
    facts: list[Fact] = []
    standout: str | None = None
    suggestion: str | None = None
    salvaged: bool = False


class OrchestratorResponse(BaseModel):
    provider: str
    model_id: str
    mode: str
    thinking: str | None = None
    content: str | None = None
    raw_xml: str | None = None
    disk_report: DiskReport | None = None
    process_report: ProcessReport | None = None
    commands_run: list[CommandRun] = []
