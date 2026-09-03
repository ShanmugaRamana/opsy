from pydantic import BaseModel, Field


class OrchestratorRequest(BaseModel):
    provider: str
    model_id: str
    message: str = Field(min_length=1)


class OrchestratorResponse(BaseModel):
    provider: str
    model_id: str
    thinking: str | None
    content: str
    raw_xml: str
