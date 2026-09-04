from pydantic import BaseModel


class PreferencesRecord(BaseModel):
    always_approve_commands: bool


class PreferencesUpdate(BaseModel):
    always_approve_commands: bool
