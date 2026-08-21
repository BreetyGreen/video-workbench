from pydantic import BaseModel


class SetupPreferencesUpdate(BaseModel):
    local_mode_confirmed: bool
