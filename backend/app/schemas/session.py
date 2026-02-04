from datetime import datetime

from pydantic import BaseModel


class SessionCreate(BaseModel):
    title: str | None = None


class SessionResponse(BaseModel):
    id: str
    title: str | None
    created_at: datetime
