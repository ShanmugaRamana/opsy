from datetime import datetime

from pydantic import BaseModel


class UserRecord(BaseModel):
    id: int
    name: str
    profile_pic: str
    linux_experience: str
    role_use_case: str
    created_at: datetime
