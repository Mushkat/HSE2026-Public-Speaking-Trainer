from __future__ import annotations

STEP_BANDS: dict[str, tuple[int, int]] = {
    "preprocess": (0, 25),
    "asr": (25, 50),
    "metrics": (50, 75),
    "coaching": (75, 100),
}

STEP_ALIAS_TO_BAND: dict[str, str] = {
    "queued": "preprocess",
    "waiting_for_start": "preprocess",
    "visual": "metrics",
    "finalize": "coaching",
    "ready": "coaching",
}


def clamp_progress(progress: int | float | None) -> int | None:
    if progress is None:
        return None
    return max(0, min(100, int(progress)))


def progress_for(step: str, subprogress: int | float | None = None) -> int:
    band_key = STEP_ALIAS_TO_BAND.get(step, step)
    start, end = STEP_BANDS.get(band_key, (0, 100))
    if subprogress is None:
        return start
    value = float(subprogress)
    ratio = value / 100 if value > 1 else value
    ratio = max(0.0, min(1.0, ratio))
    return clamp_progress(start + (end - start) * ratio) or start
