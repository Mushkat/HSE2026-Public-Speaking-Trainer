from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.media import Media as MediaModel
from app.models.session import Session as SessionModel
from app.models.status import Status as StatusModel
from app.models.transcript import Transcript as TranscriptModel
from app.models.user import User
from app.worker_tasks import process_analysis_job


def _build_session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def test_process_analysis_job_persists_transcript_schema(monkeypatch, tmp_path):
    SessionFactory = _build_session_factory()
    db = SessionFactory()

    user = User(email="asr@example.com", password_hash="hash")
    db.add(user)
    db.commit()
    db.refresh(user)

    session = SessionModel(user_id=user.id, title="ASR media")
    db.add(session)
    db.commit()
    db.refresh(session)

    input_media_path = tmp_path / "input.mp4"
    input_media_path.write_bytes(b"fake-media")

    media = MediaModel(
        session_id=session.id,
        original_filename="input.mp4",
        mime_type="video/mp4",
        size_bytes=9,
        storage_path=str(input_media_path),
    )
    status = StatusModel(session_id=session.id, status="queued", step="queued", progress=0)
    db.add(media)
    db.add(status)
    db.commit()

    monkeypatch.setattr("app.worker_tasks.SessionLocal", SessionFactory)
    monkeypatch.setattr(
        "app.worker_tasks.probe_media",
        lambda path: {"duration_seconds": 10.0, "sample_rate": 16000, "channels": 1}
        if str(path).endswith(".wav")
        else {"duration_seconds": 10.0, "sample_rate": 48000, "channels": 2},
    )
    monkeypatch.setattr("app.worker_tasks.settings.storage_root", str(tmp_path))
    monkeypatch.setattr("app.worker_tasks.convert_to_wav", lambda _input, output: (Path(output).parent.mkdir(parents=True, exist_ok=True), Path(output).write_bytes(b"fake-audio")))
    monkeypatch.setattr("app.worker_tasks._storage_root_path", lambda: tmp_path)
    monkeypatch.setattr(
        "app.worker_tasks.transcribe_audio",
        lambda _audio: {
            "language": "en",
            "text": "hello world",
            "words": [
                {"token": "hello", "start": 0.0, "end": 0.3, "confidence": 0.95, "low_confidence": False},
                {"token": "world", "start": 0.31, "end": 0.6, "confidence": 0.42, "low_confidence": True},
            ],
            "duration": 10.0,
        },
    )
    monkeypatch.setattr("app.worker_tasks.time.sleep", lambda _seconds: None)

    process_analysis_job(str(session.id))

    transcript = db.query(TranscriptModel).filter(TranscriptModel.session_id == session.id).first()
    assert transcript is not None
    assert transcript.language == "en"
    assert transcript.text == "hello world"
    assert isinstance(transcript.words, list)
    assert transcript.words[1]["low_confidence"] is True

    updated_status = db.query(StatusModel).filter(StatusModel.session_id == session.id).first()
    assert updated_status is not None
    assert updated_status.status == "ready"
    assert 0 <= updated_status.progress <= 100

    db.expire_all()
    updated_session = db.query(SessionModel).filter(SessionModel.id == session.id).first()
    assert updated_session is not None
    assert updated_session.analysis_results is not None
    assert "speech" in updated_session.analysis_results
    assert "wpm_avg" in updated_session.analysis_results["speech"]["metrics"]
    assert updated_session.analysis_results["speech"]["metrics"]["wpm_category"] in {"below", "normal", "above"}

    db.close()
