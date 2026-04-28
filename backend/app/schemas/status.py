from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

AllowedStatus = Literal["queued", "processing", "ready", "error"]


class StatusResponse(BaseModel):
    session_id: str
    status: AllowedStatus
    step: str | None
    progress: int | None = Field(default=None, ge=0, le=100)
    error_message: str | None
    updated_at: datetime | None

    @field_validator("step")
    @classmethod
    def normalize_step(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None
