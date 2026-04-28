import uuid
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.progress import clamp_progress, progress_for
from app.models.base import Base
from app.models.media import Media as MediaModel
from app.models.session import Session as SessionModel
from app.models.status import Status as StatusModel
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


def test_process_analysis_job_sets_error_for_duration_limit(monkeypatch, tmp_path):
    SessionFactory = _build_session_factory()
    db = SessionFactory()

    user = User(email="worker@example.com", password_hash="hash")
    db.add(user)
    db.commit()
    db.refresh(user)

    session = SessionModel(user_id=user.id, title="Long media")
    db.add(session)
    db.commit()
    db.refresh(session)

    media_path = tmp_path / "input.mp4"
    media_path.write_bytes(b"fake")

    media = MediaModel(
        session_id=session.id,
        original_filename="input.mp4",
        mime_type="video/mp4",
        size_bytes=4,
        duration_seconds=None,
        storage_path=str(media_path),
    )
    status = StatusModel(session_id=session.id, status="queued", step="queued", progress=0)
    db.add(media)
    db.add(status)
    db.commit()

    monkeypatch.setattr("app.worker_tasks.SessionLocal", SessionFactory)
    monkeypatch.setattr(
        "app.worker_tasks.probe_media",
        lambda _path: {"duration_seconds": 1300.0, "sample_rate": 48000, "channels": 2},
    )

    process_analysis_job(str(session.id))

    updated = db.query(StatusModel).filter(StatusModel.session_id == session.id).first()
    assert updated is not None
    assert updated.status == "error"
    assert updated.step == "preprocess"
    assert updated.error_message == "Duration limit exceeded (20 min)"

    db.close()


def test_clamp_progress_int_range():
    assert clamp_progress(-5) == 0
    assert clamp_progress(150) == 100
    assert clamp_progress(42.9) == 42
    assert clamp_progress(None) is None


def test_progress_for_even_bands():
    assert progress_for("preprocess", 0) == 0
    assert progress_for("preprocess", 1) == 25
    assert progress_for("asr", 0) == 25
    assert progress_for("asr", 1) == 50
    assert progress_for("metrics", 0.5) == 62
    assert progress_for("coaching", 1) == 100
    assert progress_for("finalize", 0.5) == 87
