import uuid

from app.models.session import Session as SessionModel
from app.models.status import Status as StatusModel
from app.models.transcript_segment import TranscriptSegment

from test_sessions import register_and_login


def _auth(email: str, client):
    token = register_and_login(client, email)
    return {"Authorization": f"Bearer {token}"}


def test_results_schema_v1_and_required_keys(client, db_session):
    headers = _auth("contract-owner@example.com", client)
    session_id = client.post("/sessions", json={"title": "Contract"}, headers=headers).json()["id"]
    session_uuid = uuid.UUID(session_id)

    db_session.query(SessionModel).filter(SessionModel.id == session_uuid).update(
        {
            SessionModel.analysis_results: {
                "schema_version": 1,
                "session_id": session_id,
                "generated_at": "2025-01-01T00:00:00",
                "status": "ready",
                "meta": {"language": "ru", "duration_sec": 11, "audio_format": "wav", "model_versions": {}},
                "delivery": {"tempo": {}, "pauses": {}},
                "word_choice": {"fillers": {}, "templates": {"sentence_starters": {"items": []}}, "repetitions": {}, "weak_words": {}, "conciseness": {}},
                "voice": {"pitch": {}, "loudness": {}},
                "visual": {"centering": {}, "stability": {}, "eye_contact": {}},
                "coaching": {"strength": {"title": "Сила", "text": "ok", "rating": "good"}, "growth": {"title": "Область роста", "bullets": ["x"], "rating": "ok"}, "questions": {"title": "Вопросы аудитории", "items": ["x"]}, "summary": {"title": "Резюме", "bullets": ["x"]}},
            }
        }
    )
    db_session.add(StatusModel(session_id=session_uuid, status="ready", step="ready", progress=100))
    db_session.commit()

    response = client.get(f"/sessions/{session_id}/results", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["schema_version"] == 1
    for key in ("meta", "delivery", "word_choice", "voice", "visual", "coaching"):
        assert key in data


def test_summary_contains_pr_fields(client, db_session):
    headers = _auth("summary-owner@example.com", client)
    session_id = client.post("/sessions", json={"title": "Summary"}, headers=headers).json()["id"]
    session_uuid = uuid.UUID(session_id)
    db_session.query(SessionModel).filter(SessionModel.id == session_uuid).update(
        {
            SessionModel.analysis_results: {
                "schema_version": 1,
                "session_id": session_id,
                "generated_at": "2025-01-01T00:00:00",
                "status": "ready",
                "meta": {"language": "ru", "duration_sec": 20, "audio_format": "wav", "model_versions": {}},
                "delivery": {"tempo": {"wpm_avg": {"value": 145}, "wpm_category": "normal"}, "pauses": {"pause_ratio": {"value": 0.18}}},
                "word_choice": {
                    "fillers": {"count": {"value": 2}},
                    "templates": {"sentence_starters": {"items": [{"starter": "мы"}]}},
                    "repetitions": {},
                    "weak_words": {"count": {"value": 1}},
                    "conciseness": {"redundancy_score": {"value": 0.2}},
                },
                "voice": {"pitch": {"cv": {"value": 0.22}, "label": "выразительно"}, "loudness": {"rms_cv": {"value": 0.2}, "label": "стабильно"}},
                "visual": {"centering": {"value": 80}, "stability": {"value": 75}, "eye_contact": {"value": 4}},
                "coaching": {},
            }
        }
    )
    db_session.add(StatusModel(session_id=session_uuid, status="ready", step="ready", progress=100))
    db_session.commit()

    response = client.get("/sessions/summary", headers=headers)
    assert response.status_code == 200
    summary = response.json()[0]["summary"]
    for key in ("wpm_avg", "wpm_category", "pause_ratio", "filler_count", "filler_per_min", "redundancy_score", "top_starter", "weak_words_count", "pitch_cv", "rms_cv", "centering", "stability", "eye_contact"):
        assert key in summary


def test_segments_are_ordered_and_owner_protected(client, db_session):
    owner_headers = _auth("segments-owner-pr6@example.com", client)
    session_id = client.post("/sessions", json={"title": "Segments"}, headers=owner_headers).json()["id"]
    session_uuid = uuid.UUID(session_id)

    db_session.add_all(
        [
            TranscriptSegment(session_id=session_uuid, idx=2, start_sec=20.0, end_sec=30.0, text="third", word_start_idx=20, word_end_idx=30),
            TranscriptSegment(session_id=session_uuid, idx=0, start_sec=0.0, end_sec=10.0, text="first", word_start_idx=0, word_end_idx=10),
            TranscriptSegment(session_id=session_uuid, idx=1, start_sec=10.0, end_sec=20.0, text="second", word_start_idx=10, word_end_idx=20),
        ]
    )
    db_session.commit()

    segments_response = client.get(f"/sessions/{session_id}/segments", headers=owner_headers)
    assert segments_response.status_code == 200
    idxs = [segment["idx"] for segment in segments_response.json()]
    assert idxs == [0, 1, 2]

    intruder_headers = _auth("segments-intruder-pr6@example.com", client)
    assert client.get(f"/sessions/{session_id}/segments", headers=intruder_headers).status_code == 404
    assert client.get(f"/sessions/{session_id}/results", headers=intruder_headers).status_code == 404
