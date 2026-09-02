from pydantic import BaseModel


class ModelRecord(BaseModel):
    provider: str
    model_id: str
    display_name: str
