from datetime import datetime

from pydantic import BaseModel


class MediaResponse(BaseModel):
    id: str
    session_id: str
    filename: str
    mime_type: str
    size_bytes: int
    duration_seconds: int | None
    sample_rate: int | None = None
    channels: int | None = None
    processed_audio_path: str | None = None
    storage_path: str
    created_at: datetime
