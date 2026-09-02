from pydantic import BaseModel, Field

VALID_PROVIDERS = ("anthropic", "openai", "gemini", "openrouter", "groq")


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
