from pathlib import Path
import wave

import pytest

from app.services.speech_alignment import SpeechWindow
from app.services.speech_metrics import _calculate_pauses_from_words, build_speech_metrics, map_speech_time_to_timeline_intervals


@pytest.fixture(autouse=True)
def _stub_speech_activity(monkeypatch):
    monkeypatch.setattr(
        "app.services.speech_metrics.build_speech_window",
        lambda audio_path, transcript_words=None, duration_seconds=None: SpeechWindow(
            segments=([{"start": float(transcript_words[0]["start"]), "end": float(transcript_words[-1]["end"])}] if transcript_words else []),
            speech_active_sec=(round(float(transcript_words[-1]["end"]) - float(transcript_words[0]["start"]), 4) if transcript_words else 0.0),
            window_start=(float(transcript_words[0]["start"]) if transcript_words else 0.0),
            window_end=(float(transcript_words[-1]["end"]) if transcript_words else 0.0),
            analysis_window_sec=(round(float(transcript_words[-1]["end"]) - float(transcript_words[0]["start"]), 4) if transcript_words else 0.0),
            source="test_stub",
        ),
    )



def _create_wav(path: Path, sample_rate: int = 16000, duration_seconds: int = 2):
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        total_frames = sample_rate * duration_seconds
        wav_file.writeframes((b"\x00\x00" * (sample_rate // 2)) + (b"\xff\x07" * (sample_rate // 2)) + (b"\x00\x00" * sample_rate))


def test_build_speech_metrics_contains_stage8_payload(tmp_path):
    wav_path = tmp_path / "audio.wav"
    _create_wav(wav_path)

    metrics = build_speech_metrics(
        transcript_text="ну как бы это тест",
        transcript_words=[
            {"token": "ну", "start": 0.6, "end": 0.8},
            {"token": "как", "start": 0.9, "end": 1.0},
            {"token": "бы", "start": 1.0, "end": 1.1},
            {"token": "это", "start": 1.2, "end": 1.3},
            {"token": "тест", "start": 1.4, "end": 1.6},
        ],
        audio_path=wav_path,
        duration_seconds=2.0,
    )

    assert "wpm_avg" in metrics
    assert metrics["wpm_category"] is None
    assert metrics["wpm_note"] is not None
    assert metrics["wpm_normal_range"] == {"min": 140, "max": 160}
    assert isinstance(metrics["wpm_series"], list)
    assert "pause_ratio" in metrics
    assert isinstance(metrics["pauses"], list)
    assert metrics["filler_count"] >= 1
    assert isinstance(metrics["fillers"], list)



def test_word_choice_sentence_starters_detected(tmp_path):
    wav_path = tmp_path / "audio.wav"
    _create_wav(wav_path, duration_seconds=6)
    words = []
    t = 0.0
    for token in ["Мы", "делаем", "план", ".", "Мы", "проверяем", "гипотезу", ".", "Я", "добавляю", "пример", ".", "Мы", "подводим", "итог", "."]:
        words.append({"token": token, "start": t, "end": t + 0.25})
        t += 0.3
    metrics = build_speech_metrics(
        transcript_text="Мы делаем план. Мы проверяем гипотезу. Я добавляю пример. Мы подводим итог.",
        transcript_words=words,
        audio_path=wav_path,
        duration_seconds=6.0,
    )

    starters = metrics["word_choice"]["templates"]["sentence_starters"]["items"]
    assert starters
    assert starters[0]["starter"] == "Мы"


def test_word_choice_weak_words_detects_multiword_phrase(tmp_path):
    wav_path = tmp_path / "audio.wav"
    _create_wav(wav_path, duration_seconds=6)
    words = [
        {"token": "это", "start": 0.0, "end": 0.2},
        {"token": "как", "start": 0.3, "end": 0.5},
        {"token": "бы", "start": 0.5, "end": 0.7},
        {"token": "полезно", "start": 0.8, "end": 1.0},
        {"token": "как", "start": 1.2, "end": 1.4},
        {"token": "бы", "start": 1.4, "end": 1.6},
    ]
    metrics = build_speech_metrics(
        transcript_text="Это как бы полезно, как бы.",
        transcript_words=words,
        audio_path=wav_path,
        duration_seconds=6.0,
    )

    weak_items = metrics["word_choice"]["weak_words"]["items"]
    maybe = next((item for item in weak_items if item["word"] == "как бы"), None)
    assert maybe is not None
    assert maybe["count"] == 2
    assert metrics["word_choice"]["weak_words"]["density_per_min"] > 0


def test_word_choice_redundancy_score_in_range(tmp_path):
    wav_path = tmp_path / "audio.wav"
    _create_wav(wav_path, duration_seconds=3)
    metrics = build_speech_metrics(
        transcript_text="Мы мы мы мы мы. Это это это.",
        transcript_words=[
            {"token": "Мы", "start": 0.1, "end": 0.2},
            {"token": "мы", "start": 0.3, "end": 0.4},
            {"token": "мы", "start": 0.5, "end": 0.6},
            {"token": "мы", "start": 0.7, "end": 0.8},
            {"token": "мы", "start": 0.9, "end": 1.0},
            {"token": "это", "start": 1.1, "end": 1.2},
            {"token": "это", "start": 1.3, "end": 1.4},
            {"token": "это", "start": 1.5, "end": 1.6},
        ],
        audio_path=wav_path,
        duration_seconds=3.0,
    )
    score = metrics["word_choice"]["conciseness"]["redundancy_score"]["value"]
    assert 0 <= score <= 1


def test_pauses_and_fillers_timecodes_from_words(tmp_path):
    wav_path = tmp_path / "audio.wav"
    _create_wav(wav_path, duration_seconds=8)
    words = [
        {"token": "ну", "start": 0.0, "end": 0.2},
        {"token": "мы", "start": 0.3, "end": 0.5},
        {"token": "начнем", "start": 0.6, "end": 0.9},
        {"token": "как", "start": 2.0, "end": 2.2},
        {"token": "бы", "start": 2.2, "end": 2.4},
        {"token": "с", "start": 2.5, "end": 2.6},
        {"token": "плана", "start": 2.7, "end": 3.0},
        {"token": "ну", "start": 5.5, "end": 5.7},
        {"token": "и", "start": 5.8, "end": 6.0},
        {"token": "итога", "start": 6.1, "end": 6.3},
    ]
    metrics = build_speech_metrics(
        transcript_text="",
        transcript_words=words,
        audio_path=wav_path,
        duration_seconds=8.0,
    )

    pauses = metrics["pauses"]
    assert pauses
    assert all("t" in item and item["t"] == item["start"] for item in pauses)

    fillers = metrics["fillers"]
    assert fillers
    assert all("t" in item and item["t"] == item["start"] for item in fillers)


def test_pause_ratio_basic_window_math():
    words = [
        {"token": "a", "normalized": "a", "start": 1.6, "end": 10.0},
        {"token": "b", "normalized": "b", "start": 20.0, "end": 30.0},
    ]
    speech_window = SpeechWindow(segments=[{"start": 1.6, "end": 30.0}], speech_active_sec=20.0, window_start=1.6, window_end=30.0, analysis_window_sec=28.4, source="test")
    ratio, pauses, stats = _calculate_pauses_from_words(words, speech_window, 102.5)

    assert stats["analysis_window_sec"] == 20.0
    assert ratio == round(10.0 / 30.0, 4)
    assert pauses[0]["dur"] == 10.0
    assert stats["total_pause_sec"] == 10.0
    assert stats["count"] == 1
    assert 0 <= ratio <= 1


def test_pause_ratio_trim_window_and_clamp():
    words = [
        {"token": "a", "normalized": "a", "start": 0.0, "end": 0.0},
        {"token": "b", "normalized": "b", "start": 2.0, "end": 2.3},
    ]
    speech_window = SpeechWindow(segments=[{"start": 1.5, "end": 2.3}], speech_active_sec=0.3, window_start=1.5, window_end=2.3, analysis_window_sec=0.8, source="test")
    ratio, pauses, stats = _calculate_pauses_from_words(words, speech_window, 120.0)

    assert stats["analysis_window_sec"] == 0.3
    assert pauses[0]["start"] == 1.5
    assert pauses[0]["end"] == 2.0
    assert pauses[0]["dur"] == 0.5
    assert stats["total_pause_sec"] == 0.5
    assert ratio == round(0.5 / 0.8, 4)
    assert 0 <= ratio <= 1


def test_wpm_uses_speech_active_time_not_full_duration(tmp_path, monkeypatch):
    wav_path = tmp_path / "audio.wav"
    _create_wav(wav_path, duration_seconds=5)

    transcript_words = [
        {"token": f"word{idx}", "start": float(idx) * 0.4, "end": float(idx) * 0.4 + 0.2}
        for idx in range(150)
    ]

    monkeypatch.setattr(
        "app.services.speech_metrics.build_speech_window",
        lambda audio_path, transcript_words=None, duration_seconds=None: SpeechWindow(segments=[{"start": 10.0, "end": 70.0}], speech_active_sec=60.0, window_start=10.0, window_end=70.0, analysis_window_sec=60.0, source="test"),
    )

    metrics = build_speech_metrics(
        transcript_text=" ".join(word["token"] for word in transcript_words),
        transcript_words=transcript_words,
        audio_path=wav_path,
        duration_seconds=300.0,
    )

    assert metrics["speech_active_sec"] == 60.0
    assert metrics["wpm_avg"] == 150.0
    assert metrics["wpm_avg"] != 30.0
    assert metrics["wpm_windows"]
    assert len(metrics["wpm_windows"]) == 7
    assert metrics["wpm_windows"][-1]["speech_to_sec"] == 60.0
    assert metrics["wpm_windows"][0]["seek_to_sec"] == 10.0


def test_map_speech_time_to_timeline_intervals_handles_gaps():
    speech_segments = [
        {"start": 10.0, "end": 20.0},
        {"start": 40.0, "end": 55.0},
    ]

    spans = map_speech_time_to_timeline_intervals(speech_segments, 8.0, 18.0)

    assert spans == [[18.0, 20.0], [40.0, 48.0]]


def test_wpm_windows_cover_full_speaking_time_with_gaps(tmp_path, monkeypatch):
    wav_path = tmp_path / "audio.wav"
    _create_wav(wav_path, duration_seconds=5)

    transcript_words = [
        {"token": f"word{idx}", "start": 10.0 + idx * 0.8, "end": 10.2 + idx * 0.8}
        for idx in range(10)
    ] + [
        {"token": f"later{idx}", "start": 40.0 + idx * 0.8, "end": 40.2 + idx * 0.8}
        for idx in range(10)
    ]

    monkeypatch.setattr(
        "app.services.speech_metrics.build_speech_window",
        lambda audio_path, transcript_words=None, duration_seconds=None: SpeechWindow(
            segments=[{"start": 10.0, "end": 20.0}, {"start": 40.0, "end": 55.0}],
            speech_active_sec=25.0,
            window_start=10.0,
            window_end=55.0,
            analysis_window_sec=25.0,
            source="test",
        ),
    )

    metrics = build_speech_metrics(
        transcript_text=" ".join(word["token"] for word in transcript_words),
        transcript_words=transcript_words,
        audio_path=wav_path,
        duration_seconds=120.0,
    )

    windows = metrics["wpm_windows"]
    assert len(windows) == 5
    assert windows[-1]["speech_to_sec"] == 25.0
    assert windows[-1]["timeline_spans"][-1][1] == 55.0


def test_wpm_is_null_when_speech_activity_too_short(tmp_path, monkeypatch):
    wav_path = tmp_path / "audio.wav"
    _create_wav(wav_path, duration_seconds=5)

    monkeypatch.setattr(
        "app.services.speech_metrics.build_speech_window",
        lambda audio_path, transcript_words=None, duration_seconds=None: SpeechWindow(segments=[{"start": 0.0, "end": 4.0}], speech_active_sec=4.0, window_start=0.0, window_end=4.0, analysis_window_sec=4.0, source="test"),
    )

    metrics = build_speech_metrics(
        transcript_text="одно два три",
        transcript_words=[
            {"token": "одно", "start": 0.1, "end": 0.2},
            {"token": "два", "start": 0.3, "end": 0.4},
            {"token": "три", "start": 0.5, "end": 0.6},
        ],
        audio_path=wav_path,
        duration_seconds=30.0,
    )

    assert metrics["wpm_avg"] is None
    assert metrics["wpm_category"] is None
    assert metrics["wpm_note"] is not None
