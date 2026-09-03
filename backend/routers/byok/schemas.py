from pydantic import BaseModel, Field

from routers.models.providers import CLOUD_PROVIDERS as VALID_PROVIDERS


class ApiKeyPayload(BaseModel):
    provider: str = Field(min_length=1)
    api_key: str = Field(min_length=1)


class ApiKeyVerifyResult(BaseModel):
    valid: bool
    provider: str


class ConfiguredProvider(BaseModel):
    provider: str
    key_last4: str
    verified_at: str
