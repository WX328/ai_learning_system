from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, StrictBool


class AdminUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    role: Literal["user", "admin"]
    is_active: bool
    created_at: datetime | None
    total_xp: int
    level: int


class UserStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_active: StrictBool
