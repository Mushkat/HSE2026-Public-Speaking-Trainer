from datetime import datetime
from typing import Literal

from pydantic import BaseModel


RewriteKind = Literal["short", "bullets"]


class SegmentRewriteRequest(BaseModel):
    kind: RewriteKind


class SegmentShortRewriteResponse(BaseModel):
    kind: Literal["short"]
    text: str


class SegmentBulletsRewriteResponse(BaseModel):
    kind: Literal["bullets"]
    bullets: list[str]


class SegmentRewriteEnvelope(BaseModel):
    short: SegmentShortRewriteResponse | None = None
    bullets: SegmentBulletsRewriteResponse | None = None


class SegmentResponse(BaseModel):
    id: str
    idx: int
    start_sec: float
    end_sec: float
    text: str
    rewrites: SegmentRewriteEnvelope


class SegmentRewriteRecord(BaseModel):
    id: str
    segment_id: str
    kind: RewriteKind
    content: dict
    model: str | None
    created_at: datetime | None
    updated_at: datetime | None
