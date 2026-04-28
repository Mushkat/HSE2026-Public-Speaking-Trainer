import math
from pathlib import Path

import librosa
import numpy as np
import parselmouth

from app.services.speech_alignment import filter_series_to_segments, is_in_speech_window

PITCH_TIME_STEP_SEC = 0.02
RMS_WINDOW_SEC = 0.1
SERIES_MAX_POINTS_PER_SEC = 10

PITCH_LABEL_MONOTONOUS_MAX = 0.10
PITCH_LABEL_MODERATE_MAX = 0.20

RMS_LABEL_STABLE_MAX = 0.25
RMS_LABEL_VARIATION_MAX = 0.45

MIN_VOICED_FRAMES_FOR_ASSESSMENT = 5
MIN_RMS_FRAMES_FOR_ASSESSMENT = 5


def _to_float_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    if not np.isfinite(value):
        return None
    return round(float(value), 4)


def _downsample_series(series: list[dict], min_step_sec: float) -> list[dict]:
    if not series:
        return []

    sampled: list[dict] = []
    last_t = -math.inf
    for point in series:
        t = point.get("t")
        if not isinstance(t, (int, float)):
            continue
        if t - last_t >= min_step_sec or not sampled:
            sampled.append(point)
            last_t = float(t)
    return sampled


def _pitch_label(cv_f0: float | None) -> str | None:
    if cv_f0 is None:
        return None
    if cv_f0 < PITCH_LABEL_MONOTONOUS_MAX:
        return "монотонно"
    if cv_f0 <= PITCH_LABEL_MODERATE_MAX:
        return "умеренно"
    return "выразительно"


def _loudness_label(cv_rms: float | None) -> str | None:
    if cv_rms is None:
        return None
    if cv_rms < RMS_LABEL_STABLE_MAX:
        return "стабильно"
    if cv_rms <= RMS_LABEL_VARIATION_MAX:
        return "перепады"
    return "сильные перепады"


def _empty_voice_metrics(note: str = "Недостаточно речевых кадров для оценки голоса") -> dict:
    return {
        "pitch_mean": None,
        "pitch_std": None,
        "pitch_cv": None,
        "pitch_variability_label": None,
        "pitch_series": [],
        "rms_mean": None,
        "rms_std": None,
        "rms_cv": None,
        "loudness_stability_label": None,
        "loudness_series": [],
        "scope": "speech_only",
        "note": note,
    }


def build_voice_metrics(*, audio_path: Path, sample_rate: int = 16000, speech_segments: list[dict] | None = None) -> dict:
    if not audio_path.exists():
        return _empty_voice_metrics("Аудиофайл не найден")

    signal, sr = librosa.load(str(audio_path), sr=sample_rate, mono=True)
    if signal.size == 0:
        return _empty_voice_metrics("Пустой аудиосигнал")

    speech_segments = speech_segments or []
    sound = parselmouth.Sound(signal, sampling_frequency=sr)
    pitch = sound.to_pitch(time_step=PITCH_TIME_STEP_SEC, pitch_floor=75, pitch_ceiling=350)
    frequencies = pitch.selected_array["frequency"]
    pitch_times = pitch.xs()

    pitch_series = [
        {"t": round(float(t), 3), "f0": round(float(f0), 3) if np.isfinite(f0) and f0 > 0 else None}
        for t, f0 in zip(pitch_times, frequencies)
    ]
    if speech_segments:
        pitch_series = filter_series_to_segments(pitch_series, segments=speech_segments)
    pitch_series = _downsample_series(pitch_series, min_step_sec=1 / SERIES_MAX_POINTS_PER_SEC)

    speech_pitch_mask = np.array([is_in_speech_window(float(t), speech_segments) for t in pitch_times], dtype=bool) if speech_segments else np.ones_like(frequencies, dtype=bool)
    voiced_mask = np.isfinite(frequencies) & (frequencies > 0) & speech_pitch_mask
    voiced_f0 = frequencies[voiced_mask]

    if voiced_f0.size < MIN_VOICED_FRAMES_FOR_ASSESSMENT:
        mean_f0 = None
        std_f0 = None
        cv_f0 = None
    else:
        mean_f0 = float(np.mean(voiced_f0))
        std_f0 = float(np.std(voiced_f0))
        cv_f0 = (std_f0 / mean_f0) if mean_f0 > 0 else None

    frame_length = max(1, int(RMS_WINDOW_SEC * sr))
    hop_length = frame_length
    rms = librosa.feature.rms(y=signal, frame_length=frame_length, hop_length=hop_length)[0]
    rms_times = librosa.times_like(rms, sr=sr, hop_length=hop_length)

    rms_series = [{"t": round(float(t), 3), "rms": round(float(v), 6)} for t, v in zip(rms_times, rms)]
    if speech_segments:
        rms_series = filter_series_to_segments(rms_series, segments=speech_segments)
    rms_series = _downsample_series(rms_series, min_step_sec=1 / SERIES_MAX_POINTS_PER_SEC)

    speech_rms_mask = np.array([is_in_speech_window(float(t), speech_segments) for t in rms_times], dtype=bool) if speech_segments else np.ones_like(rms, dtype=bool)
    valid_rms = rms[np.isfinite(rms) & speech_rms_mask]
    if valid_rms.size < MIN_RMS_FRAMES_FOR_ASSESSMENT:
        mean_rms = None
        std_rms = None
        cv_rms = None
    else:
        mean_rms = float(np.mean(valid_rms))
        std_rms = float(np.std(valid_rms))
        cv_rms = (std_rms / mean_rms) if mean_rms and mean_rms > 0 and std_rms is not None else None

    if voiced_f0.size < MIN_VOICED_FRAMES_FOR_ASSESSMENT and valid_rms.size < MIN_RMS_FRAMES_FOR_ASSESSMENT:
        return _empty_voice_metrics()

    return {
        "pitch_mean": _to_float_or_none(mean_f0),
        "pitch_std": _to_float_or_none(std_f0),
        "pitch_cv": _to_float_or_none(cv_f0),
        "pitch_variability_label": _pitch_label(cv_f0),
        "pitch_series": pitch_series,
        "rms_mean": _to_float_or_none(mean_rms),
        "rms_std": _to_float_or_none(std_rms),
        "rms_cv": _to_float_or_none(cv_rms),
        "loudness_stability_label": _loudness_label(cv_rms),
        "loudness_series": rms_series,
        "scope": "speech_only",
        "note": None,
    }
