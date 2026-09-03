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


class OrchestratorResponse(BaseModel):
    provider: str
    model_id: str
    mode: str
    thinking: str | None = None
    content: str | None = None
    raw_xml: str | None = None
    disk_report: DiskReport | None = None
    commands_run: list[CommandRun] = []
