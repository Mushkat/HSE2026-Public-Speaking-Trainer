from app.services.results_payload import build_session_summary, normalize_results_payload


class _SessionStub:
    def __init__(self):
        self.id = "00000000-0000-0000-0000-000000000001"
        self.created_at = "2025-01-01T00:00:00"
        self.title = "Stub"
        self.analysis_results = {
            "schema_version": 1,
            "session_id": self.id,
            "generated_at": "2025-01-01T00:00:00",
            "status": "ready",
            "meta": {"language": "ru", "duration_sec": 30, "audio_format": "wav", "model_versions": {}},
            "delivery": {"tempo": {}, "pauses": {}},
            "word_choice": {"fillers": {"density": {"value": 1.5}}, "templates": {"sentence_starters": {"items": []}}, "repetitions": {}, "weak_words": {}, "conciseness": {}},
            "voice": {"pitch": {}, "loudness": {}},
            "visual": {
                "centering": {"value": 82.0, "rating": "good", "note": "Идеально по центру"},
                "stability": {"value": 75.0, "rating": "ok", "note": "Умеренные движения"},
                "eye_contact": {"value": 4, "rating": "ok", "note": "Хороший зрительный контакт", "ratio": 0.66},
            },
            "coaching": {},
        }


def test_normalize_results_payload_keeps_visual_fields():
    payload = normalize_results_payload(
        session_id="s1",
        session_status="ready",
        stored_results={
            "schema_version": 1,
            "session_id": "s1",
            "generated_at": "2025-01-01T00:00:00",
            "status": "ready",
            "meta": {"language": "ru", "duration_sec": 10, "audio_format": "wav", "model_versions": {}},
            "delivery": {"tempo": {}, "pauses": {}},
            "word_choice": {"fillers": {}, "templates": {"sentence_starters": {"items": []}}, "repetitions": {}, "weak_words": {}, "conciseness": {}},
            "voice": {"pitch": {}, "loudness": {}},
            "visual": {
                "centering": {"value": 70.0, "rating": "ok", "note": "Небольшое смещение"},
                "stability": {"value": None, "rating": "na", "note": "Не удалось оценить позу"},
                "eye_contact": {"value": 3, "rating": "ok", "note": "Зрительный контакт нестабилен", "ratio": 0.5},
            },
            "coaching": {},
        },
    )

    assert payload["visual"]["centering"]["value"] == 70.0
    assert payload["visual"]["centering"]["rating"] == "ok"
    assert payload["visual"]["centering"]["unit"] == "score_0_100"
    assert payload["visual"]["stability"]["value"] is None
    assert payload["visual"]["stability"]["rating"] == "na"
    assert payload["visual"]["eye_contact"]["value"] == 3.0
    assert payload["visual"]["eye_contact"]["ratio"] == 0.5


def test_build_session_summary_includes_visual_metrics():
    session = _SessionStub()
    summary = build_session_summary(session, "ready")

    assert summary["summary"]["centering"] == 82.0
    assert summary["summary"]["stability"] == 75.0
    assert summary["summary"]["eye_contact"] == 4.0
    assert summary["summary"]["filler_per_min"] == 1.5



def test_normalize_results_payload_word_choice_fields_exist():
    payload = normalize_results_payload(
        session_id="s2",
        session_status="ready",
        stored_results={
            "speech": {
                "metrics": {
                    "wpm_avg": 150,
                    "wpm_category": "normal",
                    "pause_ratio": 0.2,
                    "filler_count": 2,
                    "filler_density_per_min": 1.0,
                    "fillers": [],
                    "word_choice": {
                        "templates": {"sentence_starters": {"items": [{"starter": "Мы", "ratio": 0.5, "count": 3, "timecodes": []}], "rating": "bad", "note": "test"}},
                        "repetitions": {"top_words": [{"word": "важно", "count": 4, "timecodes": []}], "top_phrases": [], "rating": "ok", "note": "test"},
                        "weak_words": {"items": [{"word": "может быть", "count": 2, "timecodes": []}], "count": 2, "rating": "ok", "note": "test"},
                        "conciseness": {"redundancy_score": {"value": 0.33, "unit": "ratio", "label": "Избыточность", "rating": "ok", "note": "test"}},
                    },
                }
            },
            "voice": {"metrics": {}},
        },
    )

    assert "sentence_starters" in payload["word_choice"]["templates"]
    assert "repetitions" in payload["word_choice"]
    assert "items" in payload["word_choice"]["weak_words"]
    assert "density_per_min" in payload["word_choice"]["weak_words"]
    assert "redundancy_score" in payload["word_choice"]["conciseness"]


def test_normalize_results_payload_exposes_speech_time_windows():
    payload = normalize_results_payload(
        session_id="speech-windows",
        session_status="ready",
        stored_results={
            "speech": {
                "metrics": {
                    "wpm_avg": 150,
                    "wpm_category": "normal",
                    "wpm_windows": [{"idx": 1, "label": "Речь 0:00–0:10", "speech_from_sec": 0.0, "speech_to_sec": 10.0, "timeline_spans": [[2.0, 14.0]], "seek_to_sec": 2.0, "speech_sec": 10.0, "words": 24, "wpm": 144.0}],
                    "pause_ratio": 0.2,
                    "fillers": [],
                    "word_choice": {"templates": {"sentence_starters": {"items": []}}, "repetitions": {}, "weak_words": {}, "conciseness": {}},
                }
            },
            "voice": {"metrics": {}},
        },
    )

    assert payload["delivery"]["tempo"]["wpm_windows"] == payload["delivery"]["tempo"]["wpm_series"]
    assert payload["delivery"]["tempo"]["wpm_windows"][0]["speech_to_sec"] == 10.0
    assert payload["delivery"]["tempo"]["wpm_windows"][0]["seek_to_sec"] == 2.0


def test_normalize_results_payload_converts_legacy_pause_percent_to_ratio():
    payload = normalize_results_payload(
        session_id="s3",
        session_status="ready",
        stored_results={
            "schema_version": 1,
            "session_id": "s3",
            "generated_at": "2025-01-01T00:00:00",
            "status": "ready",
            "meta": {"language": "ru", "duration_sec": 30, "audio_format": "wav", "model_versions": {}},
            "delivery": {
                "tempo": {},
                "pauses": {"pause_ratio": {"value": 20, "unit": "%", "label": "Доля пауз", "rating": "good", "note": ""}, "events": []},
            },
            "word_choice": {"fillers": {}, "templates": {"sentence_starters": {"items": []}}, "repetitions": {}, "weak_words": {}, "conciseness": {}},
            "voice": {"pitch": {}, "loudness": {}},
            "visual": {},
            "coaching": {},
        },
    )

    assert payload["delivery"]["pauses"]["pause_ratio"]["value"] == 0.2
    assert payload["delivery"]["pauses"]["pause_ratio"]["unit"] == "ratio"


def test_normalize_results_payload_keeps_visual_values_when_status_processing():
    payload = normalize_results_payload(
        session_id="s-processing",
        session_status="processing",
        stored_results={
            "schema_version": 1,
            "session_id": "s-processing",
            "generated_at": "2025-01-01T00:00:00",
            "status": "ready",
            "meta": {"language": "ru", "duration_sec": 10, "audio_format": "wav", "model_versions": {}},
            "delivery": {"tempo": {}, "pauses": {}},
            "word_choice": {"fillers": {}, "templates": {"sentence_starters": {"items": []}}, "repetitions": {}, "weak_words": {}, "conciseness": {}},
            "voice": {"pitch": {}, "loudness": {}},
            "visual": {
                "centering": {"value": 81.0, "rating": "good", "note": "Идеально по центру"},
                "stability": {"value": 72.0, "rating": "ok", "note": "Умеренные движения"},
                "eye_contact": {"value": 4, "rating": "ok", "note": "Хороший зрительный контакт", "ratio": 0.66},
            },
            "coaching": {},
        },
    )

    assert payload["status"] == "processing"
    assert payload["visual"]["centering"]["value"] == 81.0
    assert payload["visual"]["stability"]["value"] == 72.0
    assert payload["visual"]["eye_contact"]["value"] == 4.0


def test_normalize_legacy_results_keeps_visual_metrics():
    payload = normalize_results_payload(
        session_id="legacy-visual",
        session_status="ready",
        stored_results={
            "summary": {"language": "ru", "duration_seconds": 45},
            "speech": {"metrics": {}},
            "voice": {"metrics": {}},
            "visual": {
                "centering": {"value": 88.0, "rating": "good", "note": "Идеально по центру"},
                "stability": {"value": 79.0, "rating": "ok", "note": "Умеренные движения"},
                "eye_contact": {"value": 4, "rating": "ok", "note": "Хороший зрительный контакт", "ratio": 0.65},
            },
        },
    )

    assert payload["visual"]["centering"]["value"] == 88.0
    assert payload["visual"]["stability"]["value"] == 79.0
    assert payload["visual"]["eye_contact"]["value"] == 4.0


def test_normalize_results_payload_preserves_persisted_coaching_items():
    payload = normalize_results_payload(
        session_id="coaching-preserve",
        session_status="ready",
        stored_results={
            "schema_version": 1,
            "session_id": "coaching-preserve",
            "generated_at": "2025-01-01T00:00:00",
            "status": "ready",
            "meta": {"language": "ru", "duration_sec": 30, "audio_format": "wav", "model_versions": {}},
            "delivery": {"tempo": {}, "pauses": {}},
            "word_choice": {"fillers": {}, "templates": {"sentence_starters": {"items": []}}, "repetitions": {}, "weak_words": {}, "conciseness": {}},
            "voice": {"pitch": {}, "loudness": {}},
            "visual": {},
            "coaching": {
                "questions": {"title": "Вопросы аудитории", "items": ["Q1?", "Q2?", "Q3?"]},
                "summary": {"title": "Резюме", "bullets": ["B1", "B2", "B3"]},
            },
        },
    )

    assert payload["coaching"]["questions"]["items"] == ["Q1?", "Q2?", "Q3?"]
    assert payload["coaching"]["summary"]["bullets"] == ["B1", "B2", "B3"]
