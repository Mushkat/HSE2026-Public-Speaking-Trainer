from datetime import datetime

from pydantic import BaseModel, Field


class TranscriptWord(BaseModel):
    token: str
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    confidence: float | None = Field(default=None, ge=0, le=1)
    low_confidence: bool = False


class TranscriptResponse(BaseModel):
    session_id: str
    language: str | None
    text: str | None
    words: list[TranscriptWord]
    updated_at: datetime | None


class TranscriptPatchRequest(BaseModel):
    text: str = Field(min_length=1)
    language: str | None = None
