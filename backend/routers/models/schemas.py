from pydantic import BaseModel


class ModelRecord(BaseModel):
    provider: str
    provider_display_name: str
    model_id: str
    display_name: str
