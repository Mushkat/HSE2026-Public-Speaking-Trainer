from datetime import datetime

from pydantic import BaseModel


class MediaResponse(BaseModel):
    id: str
    session_id: str
    filename: str
    mime_type: str
    size_bytes: int
    duration_seconds: int | None
    storage_path: str
    created_at: datetime
