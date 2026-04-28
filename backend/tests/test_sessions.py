import uuid
from io import BytesIO

from sqlalchemy import text

from app.models.media import Media as MediaModel
from app.models.session import Session as SessionModel
from app.models.status import Status as StatusModel
from app.models.transcript import Transcript as TranscriptModel


def register_and_login(client, email: str):
    client.post("/auth/register", json={"email": email, "password": "Password123"})
    response = client.post(
        "/auth/login",
        data={"username": email, "password": "Password123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return response.json()["access_token"]


def upload_dummy_media(client, session_id: str, headers: dict[str, str]):
    return client.post(
        f"/sessions/{session_id}/media",
        headers=headers,
        files={"file": ("sample.wav", BytesIO(b"fake wav data"), "audio/wav")},
    )


class DummyQueue:
    def enqueue(self, *_args, **_kwargs):
        class DummyJob:
            id = "dummy-job-id"

        return DummyJob()


class CountingQueue:
    def __init__(self):
        self.calls = 0

    def enqueue(self, *_args, **_kwargs):
        self.calls += 1

        class DummyJob:
            id = "dummy-job-id"

        return DummyJob()


def test_session_flow(client):
    token = register_and_login(client, "owner@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    create_response = client.post("/sessions", json={"title": "My Session"}, headers=headers)
    assert create_response.status_code == 201
    session_data = create_response.json()

    list_response = client.get("/sessions", headers=headers)
    assert list_response.status_code == 200
    list_data = list_response.json()
    assert len(list_data) == 1
    assert list_data[0]["id"] == session_data["id"]


def test_start_analysis_requires_media(client):
    token = register_and_login(client, "owner-start@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    session_id = client.post("/sessions", json={"title": "No media"}, headers=headers).json()["id"]

    response = client.post(f"/sessions/{session_id}/start", headers=headers)
    assert response.status_code == 400
    assert response.json()["detail"] == "Upload media before starting analysis"


def test_other_user_cannot_access_session_or_analysis_routes(client):
    owner_token = register_and_login(client, "owner2@example.com")
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    session_id = client.post("/sessions", json={"title": "Private"}, headers=owner_headers).json()["id"]

    other_token = register_and_login(client, "intruder@example.com")
    other_headers = {"Authorization": f"Bearer {other_token}"}

    assert client.get(f"/sessions/{session_id}", headers=other_headers).status_code == 404
    assert client.post(f"/sessions/{session_id}/start", headers=other_headers).status_code == 404
    assert client.post(f"/sessions/{session_id}/reanalyze", headers=other_headers).status_code == 404
    assert client.get(f"/sessions/{session_id}/status", headers=other_headers).status_code == 404
    assert client.get(f"/sessions/{session_id}/results", headers=other_headers).status_code == 404


def test_start_and_reanalyze_queue_processing(client, monkeypatch):
    monkeypatch.setattr("app.api.routes.sessions.get_analysis_queue", lambda: DummyQueue())

    token = register_and_login(client, "owner3@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    session_id = client.post("/sessions", json={"title": "Requeue"}, headers=headers).json()["id"]
    upload_response = upload_dummy_media(client, session_id, headers)
    assert upload_response.status_code == 201

    start_response = client.post(f"/sessions/{session_id}/start", headers=headers)
    assert start_response.status_code == 200
    assert start_response.json()["status"] == "queued"
    assert start_response.json()["step"] == "queued"
    assert start_response.json()["progress"] == 0

    status_response = client.get(f"/sessions/{session_id}/status", headers=headers)
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "queued"

    reanalyze_response = client.post(f"/sessions/{session_id}/reanalyze", headers=headers)
    assert reanalyze_response.status_code == 200
    assert reanalyze_response.json()["status"] == "queued"




def test_start_from_waiting_for_start_queues_job(client, db_session, monkeypatch):
    monkeypatch.setattr("app.api.routes.sessions.get_analysis_queue", lambda: DummyQueue())

    token = register_and_login(client, "owner-waiting@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    session_id = client.post("/sessions", json={"title": "Waiting state"}, headers=headers).json()["id"]
    upload_response = upload_dummy_media(client, session_id, headers)
    assert upload_response.status_code == 201

    status_response = client.get(f"/sessions/{session_id}/status", headers=headers)
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "queued"
    assert status_response.json()["step"] == "waiting_for_start"

    start_response = client.post(f"/sessions/{session_id}/start", headers=headers)
    assert start_response.status_code == 200
    assert start_response.json()["status"] == "queued"
    assert start_response.json()["step"] == "queued"
    assert start_response.json()["progress"] == 0

def test_upload_second_media_rejected(client):
    token = register_and_login(client, "owner4@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    session_id = client.post("/sessions", json={"title": "One media"}, headers=headers).json()["id"]

    first_upload = upload_dummy_media(client, session_id, headers)
    assert first_upload.status_code == 201

    second_upload = upload_dummy_media(client, session_id, headers)
    assert second_upload.status_code == 409
    assert second_upload.json()["detail"] == "This session already has media. Create a new session to upload another file."


def test_upload_media_by_url_rejects_ssrf_hosts(client):
    token = register_and_login(client, "owner-url-ssrf@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    session_id = client.post("/sessions", json={"title": "URL upload"}, headers=headers).json()["id"]

    response = client.post(
        f"/sessions/{session_id}/media-url",
        json={"url": "http://127.0.0.1:9000/video.mp4"},
        headers=headers,
    )
    assert response.status_code == 400
    assert "Небезопасный адрес ссылки" in response.json()["detail"]


def test_upload_media_by_url_rejects_youtube(client):
    token = register_and_login(client, "owner-url-youtube@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    session_id = client.post("/sessions", json={"title": "URL upload"}, headers=headers).json()["id"]

    response = client.post(
        f"/sessions/{session_id}/media-url",
        json={"url": "https://www.youtube.com/watch?v=abc123"},
        headers=headers,
    )
    assert response.status_code == 400
    assert "YouTube/RuTube" in response.json()["detail"]


def test_upload_media_by_url_enforces_stream_size_guard(client, monkeypatch):
    token = register_and_login(client, "owner-url-size@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    session_id = client.post("/sessions", json={"title": "URL upload"}, headers=headers).json()["id"]

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "video/mp4"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def iter_bytes(self, chunk_size=1024):  # noqa: ARG002
            yield b"\x00\x00\x00\x18ftypisom"
            yield b"a" * (500 * 1024 * 1024)

    class FakeClient:
        def __init__(self, *args, **kwargs):  # noqa: ARG002
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def stream(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr("app.api.routes.sessions.httpx.Client", FakeClient)
    monkeypatch.setattr("app.services.url_resolver.socket.getaddrinfo", lambda *_args, **_kwargs: [(None, None, None, None, ("8.8.8.8", 0))])

    response = client.post(
        f"/sessions/{session_id}/media-url",
        json={"url": "https://cdn.example.com/video.mp4"},
        headers=headers,
    )
    assert response.status_code == 413


def test_delete_session_removes_related_rows_and_enforces_ownership(client, db_session):
    owner_token = register_and_login(client, "owner-delete@example.com")
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    session_id = client.post("/sessions", json={"title": "Delete me"}, headers=owner_headers).json()["id"]

    upload_response = upload_dummy_media(client, session_id, owner_headers)
    assert upload_response.status_code == 201

    session_uuid = uuid.UUID(session_id)
    owner_session = db_session.query(SessionModel).filter(SessionModel.id == session_uuid).first()
    db_session.add(StatusModel(session_id=owner_session.id, status="queued", step="queued", progress=0))
    db_session.add(TranscriptModel(session_id=owner_session.id, language="en", text="stub", words={}))
    db_session.commit()

    intruder_token = register_and_login(client, "intruder-delete@example.com")
    intruder_headers = {"Authorization": f"Bearer {intruder_token}"}
    assert client.delete(f"/sessions/{session_id}", headers=intruder_headers).status_code == 404

    delete_response = client.delete(f"/sessions/{session_id}", headers=owner_headers)
    assert delete_response.status_code == 204

    assert client.get(f"/sessions/{session_id}", headers=owner_headers).status_code == 404
    assert db_session.query(SessionModel).filter(SessionModel.id == session_uuid).first() is None
    assert db_session.query(MediaModel).filter(MediaModel.session_id == session_uuid).first() is None
    assert db_session.query(StatusModel).filter(StatusModel.session_id == session_uuid).first() is None
    assert db_session.query(TranscriptModel).filter(TranscriptModel.session_id == session_uuid).first() is None


def test_list_sessions_includes_speech_summary(client, db_session):
    token = register_and_login(client, "summary@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    session_id = client.post("/sessions", json={"title": "With summary"}, headers=headers).json()["id"]

    session = db_session.query(SessionModel).filter(SessionModel.id == uuid.UUID(session_id)).first()
    assert session is not None
    session.analysis_results = {
        "speech": {
            "metrics": {
                "wpm_avg": 152,
                "wpm_category": "normal",
                "pause_ratio": 0.21,
                "filler_count": 3,
            }
        },
        "voice": {
            "metrics": {
                "pitch_cv": 0.16,
                "pitch_variability_label": "умеренно",
                "rms_cv": 0.2,
                "loudness_stability_label": "стабильно"
            }
        }
    }
    db_session.commit()

    list_response = client.get("/sessions", headers=headers)
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload[0]["speech_summary"]["wpm_avg"] == 152
    assert payload[0]["speech_summary"]["wpm_category"] == "normal"
    assert payload[0]["voice_summary"]["pitch_cv"] == 0.16
    assert payload[0]["voice_summary"]["loudness_label"] == "стабильно"


def test_results_endpoint_returns_schema_v1_even_when_processing(client):
    token = register_and_login(client, "results-processing@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    session_id = client.post("/sessions", json={"title": "Schema v1"}, headers=headers).json()["id"]

    response = client.get(f"/sessions/{session_id}/results", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == 1
    for key in ["meta", "delivery", "word_choice", "voice", "visual", "coaching"]:
        assert key in payload
    assert payload["status"] == "processing"


def test_results_endpoint_normalizes_old_payload(client, db_session):
    token = register_and_login(client, "results-old@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    session_id = client.post("/sessions", json={"title": "Old payload"}, headers=headers).json()["id"]
    session_uuid = uuid.UUID(session_id)

    session = db_session.query(SessionModel).filter(SessionModel.id == session_uuid).first()
    db_session.add(StatusModel(session_id=session.id, status="ready", step="ready", progress=100))
    session.analysis_results = {
        "speech": {"metrics": {"wpm_avg": 150, "wpm_category": "normal", "pause_ratio": 0.2, "filler_count": 2}},
        "voice": {"metrics": {"pitch_cv": 0.12, "rms_cv": 0.21}},
    }
    db_session.commit()

    response = client.get(f"/sessions/{session_id}/results", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == 1
    assert payload["delivery"]["tempo"]["wpm_avg"]["value"] == 150
    assert payload["voice"]["pitch"]["cv"]["value"] == 0.12
    assert payload["voice"]["pitch"]["label"] is not None


def test_sessions_summary_endpoint(client, db_session):
    token = register_and_login(client, "summary-endpoint@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    session_id = client.post("/sessions", json={"title": "Summary endpoint"}, headers=headers).json()["id"]
    session_uuid = uuid.UUID(session_id)
    session = db_session.query(SessionModel).filter(SessionModel.id == session_uuid).first()
    db_session.add(StatusModel(session_id=session.id, status="ready", step="ready", progress=100))
    session.analysis_results = {
        "schema_version": 1,
        "session_id": session_id,
        "generated_at": "2025-01-01T00:00:00",
        "status": "ready",
        "meta": {"language": "ru", "duration_sec": 60, "audio_format": "wav", "model_versions": {}},
        "delivery": {
            "tempo": {"wpm_avg": {"value": 155, "unit": "wpm", "label": "Темп", "rating": "good", "note": ""}, "wpm_category": "normal", "wpm_series": [], "wpm_normal_range": {"min": 140, "max": 160}, "timecodes": [], "wpm_variability": {"value": None, "unit": "%", "label": "Вариативность темпа", "rating": "na", "note": ""}},
            "pauses": {"pause_ratio": {"value": 0.2, "unit": "ratio", "label": "Доля пауз", "rating": "good", "note": ""}, "events": []},
        },
        "word_choice": {"fillers": {"count": {"value": 3, "unit": "шт", "label": "Слова-паразиты", "rating": "ok", "note": ""}, "density": {"value": 1.5, "unit": "в минуту", "label": "Плотность паразитов", "rating": "ok", "note": ""}, "events": []}, "templates": {"sentence_starters": {"items": [{"starter": "Мы", "ratio": 0.22, "count": 2, "timecodes": []}], "rating": "ok", "note": "Часть предложений начинается одинаково"}}, "repetitions": {"top_words": [], "top_phrases": [], "rating": "ok", "note": "Повторы умеренные"}, "weak_words": {"count": {"value": 4, "unit": "шт", "label": "Слабые слова", "rating": "ok", "note": ""}, "items": []}, "conciseness": {"redundancy_score": {"value": 0.36, "unit": "ratio", "label": "Избыточность", "rating": "ok", "note": ""}}},
        "voice": {"pitch": {"cv": {"value": 0.11, "unit": "ratio", "label": "Вариативность интонации", "rating": "ok", "note": ""}, "label": "умеренно", "series": []}, "loudness": {"rms_cv": {"value": 0.2, "unit": "ratio", "label": "Стабильность громкости", "rating": "good", "note": ""}, "label": "стабильно", "series": []}},
        "visual": {"centering": {"value": 88, "unit": "score_0_100", "label": "Центрирование", "rating": "good", "note": "Идеально по центру"}, "stability": {"value": 74, "unit": "score_0_100", "label": "Стабильность позы", "rating": "ok", "note": "Умеренные движения"}},
        "coaching": {"strength": {"text": "stub"}, "growth": {"bullets": []}, "questions": {"items": []}, "summary": {"bullets": []}},
    }
    db_session.commit()

    response = client.get("/sessions/summary", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["summary"]["wpm_avg"] == 155
    assert payload[0]["summary"]["pitch_cv"] == 0.11
    assert payload[0]["summary"]["pitch_label"] == "умеренно"
    assert payload[0]["summary"]["loudness_label"] == "стабильно"
    assert "pause_ratio" in payload[0]["summary"]
    assert payload[0]["summary"]["centering"] == 88
    assert payload[0]["summary"]["stability"] == 74
    assert payload[0]["summary"]["filler_per_min"] == 1.5
    assert payload[0]["summary"]["redundancy_score"] == 0.36
    assert payload[0]["summary"]["top_starter"] == "Мы"
    assert payload[0]["summary"]["weak_words_count"] == 4



def test_results_endpoint_returns_persisted_coaching_questions(client, db_session):
    token = register_and_login(client, "results-questions@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    session_id = client.post("/sessions", json={"title": "Questions persisted"}, headers=headers).json()["id"]
    session_uuid = uuid.UUID(session_id)

    session = db_session.query(SessionModel).filter(SessionModel.id == session_uuid).first()
    db_session.add(StatusModel(session_id=session.id, status="ready", step="ready", progress=100))
    expected_items = [
        "Какие конкретные шаги вы предлагаете для внедрения решения в команде?",
        "Какие риски проекта вы считаете критичными и как планируете их снизить?",
        "Какой главный вывод вы хотите, чтобы аудитория запомнила после выступления?",
    ]
    session.analysis_results = {
        "schema_version": 1,
        "session_id": session_id,
        "generated_at": "2025-01-01T00:00:00",
        "status": "ready",
        "meta": {"language": "ru", "duration_sec": 60, "audio_format": "wav", "model_versions": {}},
        "delivery": {"tempo": {}, "pauses": {}},
        "word_choice": {"fillers": {}, "templates": {"sentence_starters": {"items": []}}, "repetitions": {}, "weak_words": {}, "conciseness": {}},
        "voice": {"pitch": {}, "loudness": {}},
        "visual": {},
        "coaching": {
            "strength": {"title": "Сила", "text": "stub", "rating": "ok"},
            "growth": {"title": "Область роста", "bullets": ["x"], "rating": "ok"},
            "questions": {"title": "Вопросы аудитории", "items": expected_items},
            "summary": {"title": "Резюме", "bullets": ["x"]},
        },
    }
    db_session.commit()

    response = client.get(f"/sessions/{session_id}/results", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["coaching"]["questions"]["items"] == expected_items



def test_results_endpoint_returns_persisted_coaching_summary(client, db_session):
    token = register_and_login(client, "results-summary@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    session_id = client.post("/sessions", json={"title": "Summary persisted"}, headers=headers).json()["id"]
    session_uuid = uuid.UUID(session_id)

    session = db_session.query(SessionModel).filter(SessionModel.id == session_uuid).first()
    db_session.add(StatusModel(session_id=session.id, status="ready", step="ready", progress=100))
    expected_bullets = [
        "Клиентский путь описан в трёх шагах и с понятной последовательностью.",
        "Риски внедрения названы заранее, вместе с мерами снижения.",
        "В финале есть конкретный следующий шаг для команды на неделю.",
    ]
    session.analysis_results = {
        "schema_version": 1,
        "session_id": session_id,
        "generated_at": "2025-01-01T00:00:00",
        "status": "ready",
        "meta": {"language": "ru", "duration_sec": 60, "audio_format": "wav", "model_versions": {}},
        "delivery": {"tempo": {}, "pauses": {}},
        "word_choice": {"fillers": {}, "templates": {"sentence_starters": {"items": []}}, "repetitions": {}, "weak_words": {}, "conciseness": {}},
        "voice": {"pitch": {}, "loudness": {}},
        "visual": {},
        "coaching": {
            "strength": {"title": "Сила", "text": "stub", "rating": "ok"},
            "growth": {"title": "Область роста", "bullets": ["x"], "rating": "ok"},
            "questions": {"title": "Вопросы аудитории", "items": ["x", "y", "z"]},
            "summary": {"title": "Резюме", "bullets": expected_bullets},
        },
    }
    db_session.commit()

    response = client.get(f"/sessions/{session_id}/results", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["coaching"]["summary"]["bullets"] == expected_bullets

def test_start_analysis_requeues_if_stuck_in_queued(client, db_session, monkeypatch):
    queue = CountingQueue()
    monkeypatch.setattr("app.api.routes.sessions.get_analysis_queue", lambda: queue)

    token = register_and_login(client, "owner-stuck-queued@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    session_id = client.post("/sessions", json={"title": "Stuck queued"}, headers=headers).json()["id"]
    upload_response = upload_dummy_media(client, session_id, headers)
    assert upload_response.status_code == 201

    first_start = client.post(f"/sessions/{session_id}/start", headers=headers)
    assert first_start.status_code == 200
    assert first_start.json()["status"] == "queued"

    session_uuid = uuid.UUID(session_id)
    status_row = db_session.query(StatusModel).filter(StatusModel.session_id == session_uuid).first()
    status_row.status = "queued"
    status_row.step = "queued"
    status_row.progress = 0
    db_session.commit()

    second_start = client.post(f"/sessions/{session_id}/start", headers=headers)
    assert second_start.status_code == 200
    assert second_start.json()["status"] == "queued"
    assert queue.calls == 2


def test_delete_session_works_when_segment_tables_missing(client, db_session):
    token = register_and_login(client, "owner-delete-missing-segments@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    session_id = client.post("/sessions", json={"title": "Delete with broken schema"}, headers=headers).json()["id"]

    upload_response = upload_dummy_media(client, session_id, headers)
    assert upload_response.status_code == 201

    db_session.execute(text("DROP TABLE segment_rewrites"))
    db_session.execute(text("DROP TABLE transcript_segments"))
    db_session.commit()

    delete_response = client.delete(f"/sessions/{session_id}", headers=headers)
    assert delete_response.status_code == 204


def test_put_and_get_session_scenario_preset_mode(client):
    token = register_and_login(client, "scenario-preset@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    session_id = client.post("/sessions", json={"title": "Scenario preset"}, headers=headers).json()["id"]

    payload = {
        "mode": "preset",
        "preset_id": "scientific_lecture",
        "structured": {
            "audience": "students",
            "tone": "calm",
            "goal": "teach",
        },
        "autopick": False,
    }
    put_response = client.put(f"/sessions/{session_id}/scenario", headers=headers, json=payload)
    assert put_response.status_code == 200
    body = put_response.json()
    assert body["scenario_mode"] == "preset"
    assert body["preset_id"] == "scientific_lecture"
    assert body["structured"]["goal"] == "teach"
    assert body["profile"]["norms"]["wpm"]["min"] == 120

    get_response = client.get(f"/sessions/{session_id}/scenario", headers=headers)
    assert get_response.status_code == 200
    assert get_response.json()["preset_id"] == "scientific_lecture"


def test_put_session_scenario_free_text_with_fallback(client, monkeypatch):
    token = register_and_login(client, "scenario-free@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    session_id = client.post("/sessions", json={"title": "Scenario free"}, headers=headers).json()["id"]

    monkeypatch.setattr("app.services.scenario_profile.is_llm_enabled", lambda: False)
    monkeypatch.setattr("app.services.scenario_profile.get_local_llm_client", lambda: None)
    payload = {
        "mode": "free_text",
        "free_text": "Лекция для студентов по физике, цель объяснить базовые понятия.",
        "autopick": True,
    }
    response = client.put(f"/sessions/{session_id}/scenario", headers=headers, json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["scenario_mode"] == "free_text"
    assert body["preset_id"] == "scientific_lecture"
    assert body["structured"]["goal"] == "teach"
