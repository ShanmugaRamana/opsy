from pydantic import BaseModel, Field


class OnboardingUserPayload(BaseModel):
    name: str = Field(min_length=1)
    profile_pic: str = Field(min_length=1)
    linux_experience: str = Field(min_length=1)
    role_use_case: str = Field(min_length=1)
