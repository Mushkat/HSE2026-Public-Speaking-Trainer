import math
import wave
from pathlib import Path

from app.services.voice_metrics import build_voice_metrics


def _make_tone_wav(path: Path, duration_sec: float = 1.5, sr: int = 16000) -> None:
    total_samples = int(duration_sec * sr)
    amplitude = 12000
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sr)
        frames = bytearray()
        for i in range(total_samples):
            value = int(amplitude * math.sin(2 * math.pi * 180 * (i / sr)))
            frames.extend(int(value).to_bytes(2, byteorder="little", signed=True))
        wav_file.writeframes(bytes(frames))


def test_build_voice_metrics_contains_stage9_payload(tmp_path):
    wav_path = tmp_path / "voice.wav"
    _make_tone_wav(wav_path)

    metrics = build_voice_metrics(audio_path=wav_path)

    assert "pitch_cv" in metrics
    assert "rms_cv" in metrics
    assert metrics["pitch_variability_label"] in {"монотонно", "умеренно", "выразительно", None}
    assert metrics["loudness_stability_label"] in {"стабильно", "перепады", "сильные перепады", None}
    assert isinstance(metrics["pitch_series"], list)
    assert isinstance(metrics["loudness_series"], list)
    assert any("f0" in point for point in metrics["pitch_series"])


def test_build_voice_metrics_masks_series_to_speech_segments(tmp_path):
    wav_path = tmp_path / "voice_masked.wav"
    _make_tone_wav(wav_path, duration_sec=3.0)

    metrics = build_voice_metrics(audio_path=wav_path, speech_segments=[{"start": 1.0, "end": 2.0}])

    assert metrics["scope"] == "speech_only"
    assert metrics["pitch_series"]
    assert metrics["loudness_series"]
    assert all(1.0 <= point["t"] <= 2.0 for point in metrics["pitch_series"])
    assert all(1.0 <= point["t"] <= 2.0 for point in metrics["loudness_series"])
