from io import BytesIO

from app.models.session import Session as SessionModel
from app.models.transcript import Transcript as TranscriptModel
from test_sessions import DummyQueue, register_and_login


def upload_dummy_media(client, session_id: str, headers: dict[str, str]):
    return client.post(
        f"/sessions/{session_id}/media",
        headers=headers,
        files={"file": ("sample.wav", BytesIO(b"fake wav data"), "audio/wav")},
    )


def test_get_transcript_requires_ownership(client, db_session):
    owner_token = register_and_login(client, "owner-tx@example.com")
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    session_id = client.post("/sessions", json={"title": "Private tx"}, headers=owner_headers).json()["id"]

    import uuid
    session = db_session.query(SessionModel).filter(SessionModel.id == uuid.UUID(session_id)).first()
    db_session.add(TranscriptModel(session_id=session.id, language="en", text="hello", words=[]))
    db_session.commit()

    intruder_token = register_and_login(client, "intruder-tx@example.com")
    intruder_headers = {"Authorization": f"Bearer {intruder_token}"}

    response = client.get(f"/sessions/{session_id}/transcript", headers=intruder_headers)
    assert response.status_code == 404


def test_patch_transcript_requeues_analysis(client, monkeypatch):
    monkeypatch.setattr("app.api.routes.sessions.get_analysis_queue", lambda: DummyQueue())

    token = register_and_login(client, "owner-patch@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    session_id = client.post("/sessions", json={"title": "Patch tx"}, headers=headers).json()["id"]
    assert upload_dummy_media(client, session_id, headers).status_code == 201

    patch_response = client.patch(
        f"/sessions/{session_id}/transcript",
        headers=headers,
        json={"text": "edited transcript", "language": "en"},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["text"] == "edited transcript"

    status_response = client.get(f"/sessions/{session_id}/status", headers=headers)
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "queued"
    assert status_response.json()["step"] == "queued"
