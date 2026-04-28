from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class SessionCreate(BaseModel):
    title: str | None = None


class SessionMediaUrlUpload(BaseModel):
    url: str


class SpeechSummary(BaseModel):
    wpm_avg: float | None = None
    wpm_category: str | None = None
    pause_ratio: float | None = None
    filler_count: int | None = None


class VoiceSummary(BaseModel):
    pitch_cv: float | None = None
    pitch_label: str | None = None
    rms_cv: float | None = None
    loudness_label: str | None = None


class SessionResponse(BaseModel):
    id: str
    title: str | None
    created_at: datetime
    speech_summary: SpeechSummary | None = None
    voice_summary: VoiceSummary | None = None
    scenario_preset_id: str | None = None
    scenario_label_ru: str | None = None
    scenario_goal: str | None = None


class SessionSummaryMetrics(BaseModel):
    wpm_avg: float | None
    wpm_category: Literal["below", "normal", "above"] | None
    pause_ratio: float | None
    filler_count: float | None
    filler_per_min: float | None = None
    redundancy_score: float | None = None
    top_starter: str | None = None
    weak_words_count: float | None = None
    pitch_cv: float | None
    rms_cv: float | None
    pitch_label: str | None = None
    loudness_label: str | None = None
    centering: float | None = None
    stability: float | None = None
    eye_contact: float | None = None


class SessionProgressSummaryResponse(BaseModel):
    id: str
    created_at: datetime
    title: str | None
    status: Literal["ready", "processing", "error"]
    scenario_preset_id: str | None = None
    scenario_goal: str | None = None
    scenario_label_ru: str | None = None
    summary: SessionSummaryMetrics


class SessionCommentResponse(BaseModel):
    session_id: str
    text: str | None
    updated_at: datetime | None = None


class SessionCommentUpdate(BaseModel):
    text: str | None = None


class SessionScenarioStructured(BaseModel):
    audience: str
    tone: str
    goal: str


class SessionScenarioPutRequest(BaseModel):
    mode: Literal["preset", "free_text"]
    preset_id: str | None = None
    structured: SessionScenarioStructured | None = None
    free_text: str | None = None
    autopick: bool | None = None


class SessionScenarioResponse(BaseModel):
    scenario_mode: Literal["preset", "free_text"]
    preset_id: str | None = None
    structured: dict | None = None
    free_text: str | None = None
    autopick: bool
    profile: dict | None = None
