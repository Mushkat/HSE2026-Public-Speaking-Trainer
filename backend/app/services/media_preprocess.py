from __future__ import annotations

import json
import subprocess
from pathlib import Path

TARGET_SAMPLE_RATE = 16000
TARGET_CHANNELS = 1
MAX_DURATION_SECONDS = 20 * 60


class MediaPreprocessError(Exception):
    pass


class DurationLimitExceededError(MediaPreprocessError):
    pass


def _read_probe_json(input_path: Path, timeout_seconds: int) -> dict:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,sample_rate,channels",
        "-of",
        "json",
        str(input_path),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds, check=False)
    except subprocess.TimeoutExpired as exc:
        raise MediaPreprocessError("FFprobe timeout") from exc

    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "ffprobe failed").strip()[:500]
        raise MediaPreprocessError(f"FFprobe failed: {message}")

    try:
        return json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise MediaPreprocessError("Invalid ffprobe output") from exc


def probe_media(input_path: Path, timeout_seconds: int = 60) -> dict[str, float | int | None]:
    payload = _read_probe_json(input_path, timeout_seconds)
    format_info = payload.get("format") or {}
    streams = payload.get("streams") or []

    duration_raw = format_info.get("duration")
    duration = float(duration_raw) if duration_raw is not None else None

    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    sample_rate_raw = audio_stream.get("sample_rate") if audio_stream else None
    channels_raw = audio_stream.get("channels") if audio_stream else None

    sample_rate = int(sample_rate_raw) if sample_rate_raw not in (None, "") else None
    channels = int(channels_raw) if channels_raw not in (None, "") else None

    return {
        "duration_seconds": duration,
        "sample_rate": sample_rate,
        "channels": channels,
    }


def ensure_duration_limit(duration_seconds: float | None) -> None:
    if duration_seconds is None:
        raise MediaPreprocessError("Could not determine media duration")
    if duration_seconds > MAX_DURATION_SECONDS:
        raise DurationLimitExceededError("Duration limit exceeded (20 min)")


def convert_to_wav(input_path: Path, output_path: Path, timeout_seconds: int = 120) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        str(TARGET_SAMPLE_RATE),
        "-ac",
        str(TARGET_CHANNELS),
        str(output_path),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds, check=False)
    except subprocess.TimeoutExpired as exc:
        raise MediaPreprocessError("FFmpeg timeout") from exc

    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "ffmpeg failed").strip()[:500]
        raise MediaPreprocessError(f"FFmpeg failed: {message}")
