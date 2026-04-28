from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import librosa
import numpy as np
from faster_whisper.vad import VadOptions, get_speech_timestamps

VAD_SAMPLE_RATE = 16000
TRIM_START_SEC = 1.5
TRIM_END_SEC = 1.0
VAD_MERGE_GAP_SEC = 0.35


@dataclass(slots=True)
class SpeechWindow:
    segments: list[dict[str, float]]
    speech_active_sec: float
    window_start: float
    window_end: float
    analysis_window_sec: float
    source: str


def merge_speech_segments(segments: list[dict[str, Any]], *, max_gap_sec: float = VAD_MERGE_GAP_SEC) -> list[dict[str, float]]:
    merged: list[dict[str, float]] = []
    for segment in sorted(segments, key=lambda item: float(item.get("start", 0.0) or 0.0)):
        start = float(segment.get("start", 0.0) or 0.0)
        end = float(segment.get("end", 0.0) or 0.0)
        if end <= start:
            continue
        if not merged or start - merged[-1]["end"] > max_gap_sec:
            merged.append({"start": start, "end": end})
            continue
        merged[-1]["end"] = max(merged[-1]["end"], end)
    return merged


def trim_segments_to_window(segments: list[dict[str, Any]], *, window_start: float, window_end: float) -> list[dict[str, float]]:
    trimmed: list[dict[str, float]] = []
    for segment in segments:
        start = max(window_start, float(segment.get("start", 0.0) or 0.0))
        end = min(window_end, float(segment.get("end", 0.0) or 0.0))
        if end > start:
            trimmed.append({"start": start, "end": end})
    return merge_speech_segments(trimmed)


def speech_segments_from_words(words: list[dict[str, Any]]) -> list[dict[str, float]]:
    return merge_speech_segments([
        {"start": float(word.get("start", 0.0) or 0.0), "end": float(word.get("end", 0.0) or 0.0)}
        for word in words
        if isinstance(word, dict) and isinstance(word.get("start"), (int, float)) and isinstance(word.get("end"), (int, float)) and float(word.get("end", 0.0) or 0.0) > float(word.get("start", 0.0) or 0.0)
    ])


def overlap_seconds(t_start: float, t_end: float, segments: list[dict[str, Any]]) -> float:
    overlap = 0.0
    for segment in segments:
        start = max(t_start, float(segment.get("start", 0.0) or 0.0))
        end = min(t_end, float(segment.get("end", 0.0) or 0.0))
        if end > start:
            overlap += end - start
    return overlap


def is_in_speech_window(timestamp_sec: float, segments: list[dict[str, Any]]) -> bool:
    for segment in segments:
        if float(segment.get("start", 0.0) or 0.0) <= timestamp_sec <= float(segment.get("end", 0.0) or 0.0):
            return True
    return False


def filter_series_to_segments(series: list[dict[str, Any]], *, segments: list[dict[str, Any]], time_key: str = "t") -> list[dict[str, Any]]:
    if not segments:
        return []
    filtered: list[dict[str, Any]] = []
    for item in series:
        timestamp = item.get(time_key)
        if not isinstance(timestamp, (int, float)):
            continue
        if is_in_speech_window(float(timestamp), segments):
            filtered.append(item)
    return filtered


def filter_timecodes_to_segments(timecodes: list[dict[str, Any]], *, segments: list[dict[str, Any]], time_key: str = "t") -> list[dict[str, Any]]:
    if not segments:
        return []
    return [item for item in timecodes if isinstance(item.get(time_key), (int, float)) and is_in_speech_window(float(item.get(time_key)), segments)]


def build_speech_window(*, audio_path: Path, transcript_words: list[dict[str, Any]] | None, duration_seconds: float | None) -> SpeechWindow:
    safe_duration = max(float(duration_seconds or 0.0), 0.0)
    word_segments = speech_segments_from_words(transcript_words or [])
    window_start = min(TRIM_START_SEC, safe_duration) if safe_duration > 0 else 0.0
    window_end = max(window_start, safe_duration - TRIM_END_SEC) if safe_duration > 0 else max((segment["end"] for segment in word_segments), default=0.0)

    try:
        waveform, sr = librosa.load(str(audio_path), sr=VAD_SAMPLE_RATE, mono=True)
        waveform = np.asarray(waveform, dtype=np.float32)
        if safe_duration <= 0 and sr > 0:
            safe_duration = float(len(waveform)) / float(sr)
            window_start = min(TRIM_START_SEC, safe_duration)
            window_end = max(window_start, safe_duration - TRIM_END_SEC)
        timestamps = get_speech_timestamps(
            waveform,
            vad_options=VadOptions(
                threshold=0.5,
                min_speech_duration_ms=250,
                min_silence_duration_ms=350,
                speech_pad_ms=150,
            ),
        )
        raw_segments = [
            {"start": float(item["start"]) / VAD_SAMPLE_RATE, "end": float(item["end"]) / VAD_SAMPLE_RATE}
            for item in timestamps
        ]
        segments = trim_segments_to_window(raw_segments, window_start=window_start, window_end=window_end)
        source = "vad"
    except Exception:
        segments = trim_segments_to_window(word_segments, window_start=window_start, window_end=window_end)
        source = "words_fallback"

    if not segments and word_segments:
        segments = trim_segments_to_window(word_segments, window_start=window_start, window_end=window_end)
        source = "words_fallback"

    if not segments and word_segments:
        segments = word_segments
        source = "words_fallback_untrimmed"

    speech_active_sec = round(sum(max(0.0, segment["end"] - segment["start"]) for segment in segments), 4)
    if segments:
        effective_start = segments[0]["start"]
        effective_end = segments[-1]["end"]
    else:
        effective_start = window_start
        effective_end = window_end
    analysis_window_sec = round(max(0.001, effective_end - effective_start), 4)
    return SpeechWindow(
        segments=segments,
        speech_active_sec=round(speech_active_sec, 4),
        window_start=round(effective_start, 4),
        window_end=round(effective_end, 4),
        analysis_window_sec=analysis_window_sec,
        source=source,
    )


def get_speech_segments(session_id: str, db=None) -> list[dict[str, float]]:
    owns_session = False
    if db is None:
        from app.core.database import SessionLocal
        db = SessionLocal()
        owns_session = True

    try:
        from app.models.session import Session as SessionModel
        session = db.get(SessionModel, session_id)
        if not session or not isinstance(session.analysis_results, dict):
            return []
        speech = session.analysis_results.get("speech") if isinstance(session.analysis_results.get("speech"), dict) else {}
        metrics = speech.get("metrics") if isinstance(speech.get("metrics"), dict) else {}
        segments = metrics.get("speech_segments") if isinstance(metrics.get("speech_segments"), list) else []
        return [
            {"start": float(item.get("start", 0.0) or 0.0), "end": float(item.get("end", 0.0) or 0.0)}
            for item in segments
            if isinstance(item, dict)
        ]
    finally:
        if owns_session:
            db.close()
