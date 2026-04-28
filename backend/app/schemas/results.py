from typing import Any

from pydantic import BaseModel


class ResultsResponse(BaseModel):
    schema_version: int
    session_id: str
    generated_at: str
    status: str
    meta: dict[str, Any]
    delivery: dict[str, Any]
    word_choice: dict[str, Any]
    voice: dict[str, Any]
    visual: dict[str, Any]
    coaching: dict[str, Any]
