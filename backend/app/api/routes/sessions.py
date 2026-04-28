import logging
import mimetypes
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.core.progress import clamp_progress
from app.core.queue import get_analysis_queue
from app.models.media import Media as MediaModel
from app.models.session import Session as SessionModel
from app.models.status import Status as StatusModel
from app.models.transcript import Transcript as TranscriptModel
from app.models.user import User
from app.models.transcript_segment import TranscriptSegment
from app.models.segment_rewrite import SegmentRewrite
from jose import JWTError, jwt
from fastapi.responses import FileResponse, StreamingResponse
from app.schemas.media import MediaResponse
from app.schemas.session import (
    SessionCommentResponse,
    SessionCommentUpdate,
    SessionCreate,
    SessionMediaUrlUpload,
    SessionScenarioPutRequest,
    SessionScenarioResponse,
    SessionProgressSummaryResponse,
    SessionResponse,
    SpeechSummary,
    VoiceSummary,
)
from app.schemas.status import AllowedStatus, StatusResponse
from app.schemas.results import ResultsResponse
from app.schemas.transcript import TranscriptPatchRequest, TranscriptResponse
from app.schemas.segments import (
    SegmentBulletsRewriteResponse,
    SegmentResponse,
    SegmentRewriteEnvelope,
    SegmentRewriteRequest,
    SegmentShortRewriteResponse,
)
from app.services.results_payload import build_session_summary, normalize_results_payload
from app.services.scenario_baselines import DEFAULT_PRESET_ID, DEFAULT_STRUCTURED, get_preset_label_ru
from app.services.scenario_profile import build_scenario_profile, classify_scenario_free_text
from app.services.url_resolver import resolve_media_url
from app.services.transcript_segments import (
    ensure_segments_word_indices,
    generate_segment_rewrite,
    has_segments_tables,
    rewrite_bullets_fallback,
    upsert_segment_rewrite,
)
from app.worker_tasks import process_analysis_job
from app.core.messages_ru import (
    AUTH_INVALID_TOKEN,
    FILE_TOO_LARGE,
    FILENAME_REQUIRED,
    INVALID_RANGE,
    MEDIA_FILE_NOT_FOUND,
    MEDIA_NOT_FOUND,
    SEGMENTS_UNAVAILABLE,
    SEGMENT_NOT_FOUND,
    SESSION_MEDIA_EXISTS,
    MEDIA_URL_FETCH_FAILED,
    MEDIA_URL_HTML_PAGE,
    SESSION_NOT_FOUND,
    UNSUPPORTED_FILE_TYPE,
    UPLOAD_MEDIA_BEFORE_ANALYSIS,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".webm", ".mp3", ".wav"}
ALLOWED_MIME_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/webm",
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
}
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024
ALLOWED_STATUS_VALUES: set[AllowedStatus] = {"queued", "processing", "ready", "error"}
URL_MAX_LENGTH = 2048
BLOCKED_HOSTS = {"localhost"}
BLOCKED_VIDEO_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "rutube.ru", "www.rutube.ru"}


def _sanitize_structured_scenario(value: dict | None) -> dict | None:
    if not isinstance(value, dict):
        return None
    return {
        "goal": str(value.get("goal") or DEFAULT_STRUCTURED["goal"]),
        "audience": str(value.get("audience") or DEFAULT_STRUCTURED["audience"]),
        "tone": str(value.get("tone") or DEFAULT_STRUCTURED["tone"]),
    }


def _sniff_media_type(head: bytes, header_mime: str | None, source_url: str) -> tuple[str, str]:
    mime = (header_mime or "").split(";")[0].strip().lower()
    guessed_ext = Path(urlparse(source_url).path).suffix.lower()
    if head.startswith(b"RIFF") and len(head) > 12 and head[8:12] == b"WAVE":
        return "audio/wav", ".wav"
    if head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        return "audio/mpeg", ".mp3"
    if len(head) > 12 and head[4:8] == b"ftyp":
        major = head[8:12]
        if major in {b"qt  "}:
            return "video/quicktime", ".mov"
        return "video/mp4", ".mp4"
    if head.startswith(b"\x1A\x45\xDF\xA3"):
        return "video/webm", ".webm"

    if mime in ALLOWED_MIME_TYPES:
        ext = mimetypes.guess_extension(mime) or guessed_ext
        return mime, ext.lower() if ext else ""

    if guessed_ext in ALLOWED_EXTENSIONS:
        guessed_mime = mimetypes.types_map.get(guessed_ext, "application/octet-stream")
        return guessed_mime, guessed_ext
    raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=UNSUPPORTED_FILE_TYPE)


def _looks_like_html(head: bytes, content_type: str | None) -> bool:
    text = (head[:256] or b"").lower()
    ctype = (content_type or "").lower()
    return (
        "text/html" in ctype
        or b"<html" in text
        or b"<!doctype html" in text
    )


def build_speech_summary(analysis_results: dict | None) -> SpeechSummary | None:
    if not isinstance(analysis_results, dict):
        return None

    if analysis_results.get("schema_version") == 1:
        delivery = analysis_results.get("delivery") if isinstance(analysis_results.get("delivery"), dict) else {}
        tempo = delivery.get("tempo") if isinstance(delivery.get("tempo"), dict) else {}
        pauses = delivery.get("pauses") if isinstance(delivery.get("pauses"), dict) else {}
        word_choice = analysis_results.get("word_choice") if isinstance(analysis_results.get("word_choice"), dict) else {}
        fillers = word_choice.get("fillers") if isinstance(word_choice.get("fillers"), dict) else {}

        wpm_avg = (tempo.get("wpm_avg") or {}).get("value") if isinstance(tempo.get("wpm_avg"), dict) else None
        pause_ratio = (pauses.get("pause_ratio") or {}).get("value") if isinstance(pauses.get("pause_ratio"), dict) else None
        filler_count = (fillers.get("count") or {}).get("value") if isinstance(fillers.get("count"), dict) else None
        return SpeechSummary(
            wpm_avg=float(wpm_avg) if isinstance(wpm_avg, (int, float)) else None,
            wpm_category=str(tempo.get("wpm_category")) if tempo.get("wpm_category") is not None else None,
            pause_ratio=float(pause_ratio) if isinstance(pause_ratio, (int, float)) else None,
            filler_count=int(filler_count) if isinstance(filler_count, (int, float)) else None,
        )

    speech = analysis_results.get("speech")
    metrics = speech.get("metrics") if isinstance(speech, dict) else None
    if not isinstance(metrics, dict):
        return None

    wpm_avg = metrics.get("wpm_avg")
    pause_ratio = metrics.get("pause_ratio")
    filler_count = metrics.get("filler_count")
    return SpeechSummary(
        wpm_avg=float(wpm_avg) if isinstance(wpm_avg, (int, float)) else None,
        wpm_category=str(metrics.get("wpm_category")) if metrics.get("wpm_category") is not None else None,
        pause_ratio=float(pause_ratio) if isinstance(pause_ratio, (int, float)) else None,
        filler_count=int(filler_count) if isinstance(filler_count, int) else None,
    )


def build_voice_summary(analysis_results: dict | None) -> VoiceSummary | None:
    if not isinstance(analysis_results, dict):
        return None

    if analysis_results.get("schema_version") == 1:
        voice = analysis_results.get("voice") if isinstance(analysis_results.get("voice"), dict) else {}
        pitch = voice.get("pitch") if isinstance(voice.get("pitch"), dict) else {}
        loudness = voice.get("loudness") if isinstance(voice.get("loudness"), dict) else {}
        pitch_cv = (pitch.get("cv") or {}).get("value") if isinstance(pitch.get("cv"), dict) else None
        rms_cv = (loudness.get("rms_cv") or {}).get("value") if isinstance(loudness.get("rms_cv"), dict) else None
        return VoiceSummary(
            pitch_cv=float(pitch_cv) if isinstance(pitch_cv, (int, float)) else None,
            pitch_label=(pitch.get("label") if isinstance(pitch.get("label"), str) else None)
            or ((pitch.get("cv") or {}).get("note") if isinstance(pitch.get("cv"), dict) else None),
            rms_cv=float(rms_cv) if isinstance(rms_cv, (int, float)) else None,
            loudness_label=(loudness.get("label") if isinstance(loudness.get("label"), str) else None)
            or ((loudness.get("rms_cv") or {}).get("note") if isinstance(loudness.get("rms_cv"), dict) else None),
        )

    voice = analysis_results.get("voice")
    metrics = voice.get("metrics") if isinstance(voice, dict) else None
    if not isinstance(metrics, dict):
        return None

    pitch_cv = metrics.get("pitch_cv")
    rms_cv = metrics.get("rms_cv")
    return VoiceSummary(
        pitch_cv=float(pitch_cv) if isinstance(pitch_cv, (int, float)) else None,
        pitch_label=str(metrics.get("pitch_variability_label")) if metrics.get("pitch_variability_label") is not None else None,
        rms_cv=float(rms_cv) if isinstance(rms_cv, (int, float)) else None,
        loudness_label=str(metrics.get("loudness_stability_label")) if metrics.get("loudness_stability_label") is not None else None,
    )

def normalize_progress(progress: int | None) -> int | None:
    return clamp_progress(progress)


def ensure_valid_status(value: str) -> AllowedStatus:
    if value not in ALLOWED_STATUS_VALUES:
        raise ValueError(f"Unsupported status: {value}")
    return value


def to_status_response(status_row: StatusModel, session_id: uuid.UUID) -> StatusResponse:
    return StatusResponse(
        session_id=str(session_id),
        status=ensure_valid_status(status_row.status),
        step=status_row.step,
        progress=normalize_progress(status_row.progress),
        error_message=status_row.error_message,
        updated_at=status_row.updated_at,
    )


def get_owned_session(session_id: str, current_user: User, db: Session) -> SessionModel:
    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=SESSION_NOT_FOUND)
    session = (
        db.query(SessionModel)
        .filter(SessionModel.id == session_uuid, SessionModel.user_id == current_user.id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=SESSION_NOT_FOUND)
    return session


def get_current_user_from_query_token(token: str, db: Session) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=AUTH_INVALID_TOKEN,
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        subject: str | None = payload.get("sub")
        if subject is None:
            raise credentials_exception
        user_id = uuid.UUID(subject)
    except (JWTError, ValueError):
        raise credentials_exception

    user = db.get(User, user_id)
    if user is None:
        raise credentials_exception
    return user


def enqueue_analysis(session: SessionModel, db: Session, *, from_transcript_edit: bool = False) -> StatusModel:
    status_row = db.query(StatusModel).filter(StatusModel.session_id == session.id).first()
    if not status_row:
        status_row = StatusModel(session_id=session.id, status="queued", step="queued", progress=0)
        db.add(status_row)

    status_row.status = "queued"
    status_row.step = "queued"
    status_row.progress = 0
    status_row.error_message = None
    status_row.updated_at = datetime.utcnow()
    session.analysis_results = None
    db.commit()
    db.refresh(status_row)

    job = get_analysis_queue().enqueue(process_analysis_job, str(session.id), from_transcript_edit=from_transcript_edit)
    logger.warning("analysis job enqueued", extra={"session_id": str(session.id), "job_id": job.id, "local_llm_enabled": bool(settings.local_llm_enabled), "local_llm_base_url": settings.local_llm_base_url})
    return status_row


def _storage_root_path() -> Path:
    storage_root = Path(settings.storage_root)
    return storage_root if storage_root.is_absolute() else Path.cwd() / storage_root


def _delete_media_file(storage_path: str) -> None:
    try:
        target = Path(storage_path)
        if not target.is_absolute():
            target = Path.cwd() / target
        if target.exists():
            target.unlink()
    except Exception:
        logger.exception("failed to remove media file", extra={"storage_path": storage_path})


def _build_media_response(media: MediaModel) -> MediaResponse:
    return MediaResponse(
        id=str(media.id),
        session_id=str(media.session_id),
        filename=media.original_filename,
        mime_type=media.mime_type,
        size_bytes=media.size_bytes,
        duration_seconds=media.duration_seconds,
        sample_rate=media.sample_rate,
        channels=media.channels,
        processed_audio_path=media.processed_audio_path,
        storage_path=media.storage_path,
        created_at=media.created_at,
    )


def _persist_media_row(db: Session, session: SessionModel, *, original_name: str, mime_type: str, size_bytes: int, stored_filename: str) -> MediaModel:
    relative_root = Path(settings.storage_root)
    relative_path = str(relative_root / str(session.id) / stored_filename)
    media = MediaModel(
        session_id=session.id,
        original_filename=original_name,
        mime_type=mime_type,
        size_bytes=size_bytes,
        duration_seconds=None,
        storage_path=relative_path,
    )
    db.add(media)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=SESSION_MEDIA_EXISTS,
        )
    db.refresh(media)
    return media


def to_session_comment_response(session: SessionModel) -> SessionCommentResponse:
    return SessionCommentResponse(session_id=str(session.id), text=session.comment_text, updated_at=None)


def _scenario_goal_from_session(session: SessionModel) -> str | None:
    profile = session.scenario_profile_json if isinstance(session.scenario_profile_json, dict) else {}
    if isinstance(profile.get("goal"), str):
        return profile.get("goal")
    structured = session.scenario_structured_json if isinstance(session.scenario_structured_json, dict) else {}
    if isinstance(structured.get("goal"), str):
        return structured.get("goal")
    return None


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    payload: SessionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SessionResponse:
    session = SessionModel(user_id=current_user.id, title=payload.title)
    db.add(session)
    db.commit()
    db.refresh(session)
    return SessionResponse(
        id=str(session.id),
        title=session.title,
        created_at=session.created_at,
        speech_summary=build_speech_summary(session.analysis_results),
        voice_summary=build_voice_summary(session.analysis_results),
        scenario_preset_id=session.scenario_preset_id,
        scenario_label_ru=get_preset_label_ru(session.scenario_preset_id),
        scenario_goal=_scenario_goal_from_session(session),
    )


@router.get("", response_model=list[SessionResponse])
def list_sessions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SessionResponse]:
    sessions = (
        db.query(SessionModel)
        .filter(SessionModel.user_id == current_user.id)
        .order_by(SessionModel.created_at.desc())
        .all()
    )
    return [
        SessionResponse(
            id=str(item.id),
            title=item.title,
            created_at=item.created_at,
            speech_summary=build_speech_summary(item.analysis_results),
            voice_summary=build_voice_summary(item.analysis_results),
            scenario_preset_id=item.scenario_preset_id,
            scenario_label_ru=get_preset_label_ru(item.scenario_preset_id),
            scenario_goal=_scenario_goal_from_session(item),
        )
        for item in sessions
    ]




@router.get("/summary", response_model=list[SessionProgressSummaryResponse])
def list_sessions_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SessionProgressSummaryResponse]:
    sessions = (
        db.query(SessionModel)
        .filter(SessionModel.user_id == current_user.id)
        .order_by(SessionModel.created_at.desc())
        .all()
    )
    status_rows = {row.session_id: row for row in db.query(StatusModel).filter(StatusModel.session_id.in_([s.id for s in sessions])).all()} if sessions else {}

    payload: list[SessionProgressSummaryResponse] = []
    for item in sessions:
        status_value = status_rows[item.id].status if item.id in status_rows else "processing"
        if status_value == "queued":
            status_value = "processing"
        payload.append(SessionProgressSummaryResponse(**build_session_summary(item, status_value)))
    return payload

@router.get("/{session_id}", response_model=SessionResponse)
def get_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SessionResponse:
    session = get_owned_session(session_id, current_user, db)
    return SessionResponse(
        id=str(session.id),
        title=session.title,
        created_at=session.created_at,
        speech_summary=build_speech_summary(session.analysis_results),
        voice_summary=build_voice_summary(session.analysis_results),
        scenario_preset_id=session.scenario_preset_id,
        scenario_label_ru=get_preset_label_ru(session.scenario_preset_id),
        scenario_goal=_scenario_goal_from_session(session),
    )


@router.get("/{session_id}/scenario", response_model=SessionScenarioResponse)
def get_session_scenario(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SessionScenarioResponse:
    session = get_owned_session(session_id, current_user, db)
    return SessionScenarioResponse(
        scenario_mode=session.scenario_mode if session.scenario_mode in {"preset", "free_text"} else "preset",
        preset_id=session.scenario_preset_id,
        structured=_sanitize_structured_scenario(session.scenario_structured_json),
        free_text=session.scenario_free_text,
        autopick=bool(session.scenario_autopick),
        profile=session.scenario_profile_json if isinstance(session.scenario_profile_json, dict) else None,
    )


@router.put("/{session_id}/scenario", response_model=SessionScenarioResponse)
def put_session_scenario(
    session_id: str,
    payload: SessionScenarioPutRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SessionScenarioResponse:
    session = get_owned_session(session_id, current_user, db)
    mode = payload.mode

    if mode == "preset":
        if not payload.preset_id or payload.structured is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="preset_id and structured are required for preset mode")
        structured = _sanitize_structured_scenario(payload.structured.model_dump())
        profile = build_scenario_profile(preset_id=payload.preset_id, structured=structured, user_hint="")
        session.scenario_mode = "preset"
        session.scenario_preset_id = profile["preset_id"]
        session.scenario_structured_json = structured
        session.scenario_free_text = None
        session.scenario_autopick = bool(payload.autopick) if payload.autopick is not None else False
        session.scenario_profile_json = profile
    else:
        if not payload.free_text or not payload.free_text.strip():
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="free_text is required for free_text mode")
        autopick = True if payload.autopick is None else bool(payload.autopick)
        classification_reason: str | None = None
        if autopick:
            try:
                classification, classification_reason = classify_scenario_free_text(payload.free_text)
            except Exception:
                logger.exception("Scenario free-text classification failed unexpectedly for session %s", session.id)
                classification = dict(DEFAULT_STRUCTURED)
                classification["preset_id"] = DEFAULT_PRESET_ID
                classification_reason = "unexpected_error"
        else:
            classification = dict(DEFAULT_STRUCTURED)
            classification["preset_id"] = DEFAULT_PRESET_ID
        structured = {
            "goal": classification["goal"],
            "audience": classification["audience"],
            "tone": classification["tone"],
        }
        profile = build_scenario_profile(preset_id=classification["preset_id"], structured=structured, user_hint=payload.free_text)
        session.scenario_mode = "free_text"
        session.scenario_preset_id = profile["preset_id"]
        session.scenario_structured_json = structured
        session.scenario_free_text = payload.free_text.strip()
        session.scenario_autopick = autopick
        session.scenario_profile_json = profile | {"autopick_fallback_reason": classification_reason}

    session.scenario_version = 1
    session.scenario_updated_at = datetime.utcnow()
    db.commit()
    db.refresh(session)
    return SessionScenarioResponse(
        scenario_mode=session.scenario_mode if session.scenario_mode in {"preset", "free_text"} else "preset",
        preset_id=session.scenario_preset_id,
        structured=_sanitize_structured_scenario(session.scenario_structured_json),
        free_text=session.scenario_free_text,
        autopick=bool(session.scenario_autopick),
        profile=session.scenario_profile_json if isinstance(session.scenario_profile_json, dict) else None,
    )


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    session = get_owned_session(session_id, current_user, db)
    media_items = db.query(MediaModel).filter(MediaModel.session_id == session.id).all()
    for item in media_items:
        _delete_media_file(item.storage_path)

    db.query(StatusModel).filter(StatusModel.session_id == session.id).delete(synchronize_session=False)
    db.query(TranscriptModel).filter(TranscriptModel.session_id == session.id).delete(synchronize_session=False)
    db.query(MediaModel).filter(MediaModel.session_id == session.id).delete(synchronize_session=False)
    db.query(SessionModel).filter(SessionModel.id == session.id).delete(synchronize_session=False)
    db.commit()


@router.get("/{session_id}/media", response_model=list[MediaResponse])
def list_session_media(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[MediaResponse]:
    session = get_owned_session(session_id, current_user, db)
    media_items = (
        db.query(MediaModel)
        .filter(MediaModel.session_id == session.id)
        .order_by(MediaModel.created_at.desc())
        .all()
    )
    return [
        MediaResponse(
            id=str(item.id),
            session_id=str(item.session_id),
            filename=item.original_filename,
            mime_type=item.mime_type,
            size_bytes=item.size_bytes,
            duration_seconds=item.duration_seconds,
            sample_rate=item.sample_rate,
            channels=item.channels,
            processed_audio_path=item.processed_audio_path,
            storage_path=item.storage_path,
            created_at=item.created_at,
        )
        for item in media_items
    ]


@router.post("/{session_id}/media", response_model=MediaResponse, status_code=status.HTTP_201_CREATED)
def upload_session_media(
    session_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MediaResponse:
    session = get_owned_session(session_id, current_user, db)
    if db.query(MediaModel.id).filter(MediaModel.session_id == session.id).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=SESSION_MEDIA_EXISTS,
        )

    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=FILENAME_REQUIRED)

    original_name = Path(file.filename).name
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=UNSUPPORTED_FILE_TYPE)
    if file.content_type and file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=UNSUPPORTED_FILE_TYPE)

    session_dir = _storage_root_path() / str(session.id)
    session_dir.mkdir(parents=True, exist_ok=True)
    stored_filename = f"{uuid.uuid4()}_{original_name}"
    destination_path = session_dir / stored_filename

    size_bytes = 0
    try:
        with destination_path.open("wb") as destination:
            while True:
                chunk = file.file.read(CHUNK_SIZE)
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=FILE_TOO_LARGE)
                destination.write(chunk)
    except HTTPException:
        if destination_path.exists():
            destination_path.unlink()
        raise
    finally:
        file.file.close()

    try:
        media = _persist_media_row(
            db,
            session,
            original_name=original_name,
            mime_type=file.content_type or "application/octet-stream",
            size_bytes=size_bytes,
            stored_filename=stored_filename,
        )
    except HTTPException:
        if destination_path.exists():
            destination_path.unlink()
        raise
    return _build_media_response(media)


@router.post("/{session_id}/media-url", response_model=MediaResponse, status_code=status.HTTP_201_CREATED)
def upload_session_media_by_url(
    session_id: str,
    payload: SessionMediaUrlUpload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MediaResponse:
    session = get_owned_session(session_id, current_user, db)
    if db.query(MediaModel.id).filter(MediaModel.session_id == session.id).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=SESSION_MEDIA_EXISTS)

    resolved = resolve_media_url(
        payload.url,
        blocked_hosts=BLOCKED_HOSTS,
        blocked_video_hosts=BLOCKED_VIDEO_HOSTS,
        url_max_length=URL_MAX_LENGTH,
    )
    current_url = resolved.final_url
    logger.info("media url resolved", extra={"session_id": str(session.id), "provider": resolved.provider, "input_url": payload.url, "resolved_url": current_url})
    max_redirects = 4
    first_chunk = b""
    size_bytes = 0
    destination_path: Path | None = None
    original_name = "remote_media"
    detected_mime = "application/octet-stream"
    stored_filename = ""
    session_dir = _storage_root_path() / str(session.id)
    session_dir.mkdir(parents=True, exist_ok=True)

    try:
        with httpx.Client(timeout=httpx.Timeout(connect=8.0, read=20.0, write=20.0, pool=20.0), follow_redirects=False) as client:
            for _ in range(max_redirects + 1):
                with client.stream("GET", current_url) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=MEDIA_URL_FETCH_FAILED)
                        redirected = resolve_media_url(
                            urljoin(current_url, location),
                            blocked_hosts=BLOCKED_HOSTS,
                            blocked_video_hosts=BLOCKED_VIDEO_HOSTS,
                            url_max_length=URL_MAX_LENGTH,
                        )
                        current_url = redirected.final_url
                        continue
                    if response.status_code >= 400:
                        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=MEDIA_URL_FETCH_FAILED)

                    content_length = response.headers.get("content-length")
                    if content_length and content_length.isdigit() and int(content_length) > MAX_UPLOAD_BYTES:
                        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=FILE_TOO_LARGE)

                    chunks = response.iter_bytes(chunk_size=CHUNK_SIZE)
                    try:
                        first_chunk = next(chunks)
                    except StopIteration:
                        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=MEDIA_URL_FETCH_FAILED)

                    if _looks_like_html(first_chunk, response.headers.get("content-type")):
                        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=MEDIA_URL_HTML_PAGE)

                    detected_mime, detected_ext = _sniff_media_type(first_chunk[:64], response.headers.get("content-type"), current_url)
                    if detected_ext not in ALLOWED_EXTENSIONS:
                        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=UNSUPPORTED_FILE_TYPE)

                    remote_name = Path(urlparse(current_url).path).name or f"remote_media{detected_ext}"
                    safe_name = "".join(ch for ch in remote_name if ch.isalnum() or ch in {"-", "_", "."}) or f"remote_media{detected_ext}"
                    if Path(safe_name).suffix.lower() != detected_ext:
                        safe_name = f"{Path(safe_name).stem or 'remote_media'}{detected_ext}"
                    original_name = safe_name
                    stored_filename = f"{uuid.uuid4()}_{safe_name}"
                    destination_path = session_dir / stored_filename

                    with destination_path.open("wb") as destination:
                        destination.write(first_chunk)
                        size_bytes += len(first_chunk)
                        for chunk in chunks:
                            if not chunk:
                                continue
                            size_bytes += len(chunk)
                            if size_bytes > MAX_UPLOAD_BYTES:
                                raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=FILE_TOO_LARGE)
                            destination.write(chunk)
                    break
            else:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=MEDIA_URL_FETCH_FAILED)
    except httpx.HTTPError:
        if destination_path and destination_path.exists():
            destination_path.unlink()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=MEDIA_URL_FETCH_FAILED)
    except HTTPException:
        if destination_path and destination_path.exists():
            destination_path.unlink()
        raise

    media = _persist_media_row(
        db,
        session,
        original_name=original_name,
        mime_type=detected_mime,
        size_bytes=size_bytes,
        stored_filename=stored_filename,
    )
    return _build_media_response(media)


def _parse_range_header(range_header: str, file_size: int) -> tuple[int, int] | None:
    if not range_header.startswith("bytes="):
        return None
    ranges = range_header.replace("bytes=", "", 1).split("-")
    if len(ranges) != 2:
        return None

    start_text, end_text = ranges
    try:
        if start_text == "":
            suffix = int(end_text)
            if suffix <= 0:
                return None
            start = max(file_size - suffix, 0)
            end = file_size - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else file_size - 1
    except ValueError:
        return None

    if start < 0 or end < 0 or start > end or start >= file_size:
        return None

    end = min(end, file_size - 1)
    return start, end


def _file_iterator(path: Path, start: int, end: int, chunk_size: int = 1024 * 1024):
    with path.open("rb") as source:
        source.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            read_size = min(chunk_size, remaining)
            data = source.read(read_size)
            if not data:
                break
            remaining -= len(data)
            yield data


@router.get("/media/{media_id}/stream")
def stream_media(
    media_id: str,
    request: Request,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    current_user = get_current_user_from_query_token(token, db)

    try:
        media_uuid = uuid.UUID(media_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=MEDIA_NOT_FOUND)

    media = db.get(MediaModel, media_uuid)
    if not media:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=MEDIA_NOT_FOUND)

    session = db.get(SessionModel, media.session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=MEDIA_NOT_FOUND)

    file_path = Path(media.storage_path)
    if not file_path.is_absolute():
        file_path = Path.cwd() / file_path

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=MEDIA_FILE_NOT_FOUND)

    file_size = file_path.stat().st_size
    range_header = request.headers.get("range")

    if range_header:
        parsed = _parse_range_header(range_header, file_size)
        if parsed is None:
            raise HTTPException(status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE, detail=INVALID_RANGE)

        start, end = parsed
        content_length = end - start + 1
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(content_length),
        }
        return StreamingResponse(
            _file_iterator(file_path, start, end),
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            media_type=media.mime_type,
            headers=headers,
        )

    return FileResponse(
        path=file_path,
        media_type=media.mime_type,
        filename=media.original_filename,
        headers={"Accept-Ranges": "bytes"},
    )


@router.post("/{session_id}/start", response_model=StatusResponse)
def start_session_analysis(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StatusResponse:
    session = get_owned_session(session_id, current_user, db)
    logger.warning("start analysis called", extra={"session_id": str(session.id), "user_id": str(current_user.id), "local_llm_enabled": bool(settings.local_llm_enabled)})

    media_exists = db.query(MediaModel.id).filter(MediaModel.session_id == session.id).first()
    if not media_exists:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=UPLOAD_MEDIA_BEFORE_ANALYSIS)

    existing_status = db.query(StatusModel).filter(StatusModel.session_id == session.id).first()
    if existing_status and existing_status.status == "processing":
        return to_status_response(existing_status, session.id)

    status_row = enqueue_analysis(session, db)
    return to_status_response(status_row, session.id)


@router.post("/{session_id}/reanalyze", response_model=StatusResponse)
def reanalyze_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StatusResponse:
    session = get_owned_session(session_id, current_user, db)
    media_exists = db.query(MediaModel.id).filter(MediaModel.session_id == session.id).first()
    if not media_exists:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=UPLOAD_MEDIA_BEFORE_ANALYSIS)

    status_row = enqueue_analysis(session, db)
    return to_status_response(status_row, session.id)


@router.get("/{session_id}/status", response_model=StatusResponse)
def get_session_status(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StatusResponse:
    session = get_owned_session(session_id, current_user, db)
    status_row = db.query(StatusModel).filter(StatusModel.session_id == session.id).first()
    if not status_row:
        status_row = StatusModel(session_id=session.id, status="queued", step="waiting_for_start", progress=0)
        db.add(status_row)
        db.commit()
        db.refresh(status_row)
    return to_status_response(status_row, session.id)


def to_transcript_response(session_id: uuid.UUID, transcript: TranscriptModel | None) -> TranscriptResponse:
    if not transcript:
        return TranscriptResponse(session_id=str(session_id), language=None, text=None, words=[], updated_at=None)

    words = transcript.words if isinstance(transcript.words, list) else []
    return TranscriptResponse(
        session_id=str(session_id),
        language=transcript.language,
        text=transcript.text,
        words=words,
        updated_at=transcript.updated_at,
    )


@router.get("/{session_id}/comment", response_model=SessionCommentResponse)
def get_session_comment(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SessionCommentResponse:
    session = get_owned_session(session_id, current_user, db)
    return to_session_comment_response(session)


@router.put("/{session_id}/comment", response_model=SessionCommentResponse)
def put_session_comment(
    session_id: str,
    payload: SessionCommentUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SessionCommentResponse:
    session = get_owned_session(session_id, current_user, db)
    session.comment_text = payload.text
    db.commit()
    db.refresh(session)
    return to_session_comment_response(session)


@router.get("/{session_id}/transcript", response_model=TranscriptResponse)
def get_session_transcript(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TranscriptResponse:
    session = get_owned_session(session_id, current_user, db)
    transcript = db.query(TranscriptModel).filter(TranscriptModel.session_id == session.id).first()
    return to_transcript_response(session.id, transcript)


@router.patch("/{session_id}/transcript", response_model=TranscriptResponse)
def patch_session_transcript(
    session_id: str,
    payload: TranscriptPatchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TranscriptResponse:
    session = get_owned_session(session_id, current_user, db)

    transcript = db.query(TranscriptModel).filter(TranscriptModel.session_id == session.id).first()
    if not transcript:
        transcript = TranscriptModel(session_id=session.id)
        db.add(transcript)

    transcript.text = payload.text
    if payload.language is not None:
        transcript.language = payload.language
    transcript.updated_at = datetime.utcnow()

    status_row = enqueue_analysis(session, db, from_transcript_edit=True)
    logger.info(
        "transcript updated and metrics recalculation enqueued",
        extra={"session_id": str(session.id), "status": status_row.status},
    )

    db.refresh(transcript)
    return to_transcript_response(session.id, transcript)




def _to_segment_response(segment: TranscriptSegment) -> SegmentResponse:
    short = None
    bullets = None
    for rewrite in getattr(segment, "rewrites", []) or []:
        if rewrite.kind == "short" and isinstance(rewrite.content, dict):
            short_text = rewrite.content.get("text")
            if isinstance(short_text, str):
                short = SegmentShortRewriteResponse(kind="short", text=short_text)
        if rewrite.kind == "bullets" and isinstance(rewrite.content, dict):
            bullet_values = rewrite.content.get("bullets")
            if isinstance(bullet_values, list):
                bullets = SegmentBulletsRewriteResponse(kind="bullets", bullets=[str(item) for item in bullet_values])

    return SegmentResponse(
        id=str(segment.id),
        idx=segment.idx,
        start_sec=float(segment.start_sec),
        end_sec=float(segment.end_sec),
        text=segment.text,
        rewrites=SegmentRewriteEnvelope(short=short, bullets=bullets),
    )


@router.get("/{session_id}/segments", response_model=list[SegmentResponse])
def get_session_segments(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SegmentResponse]:
    session = get_owned_session(session_id, current_user, db)
    if not has_segments_tables(db):
        logger.warning("segment tables are missing; returning empty segment list", extra={"session_id": str(session.id)})
        return []

    segments = ensure_segments_word_indices(db, session_id=session.id)

    segment_ids = [item.id for item in segments]
    rewrites_by_segment: dict = {}
    if segment_ids:
        rewrites = db.query(SegmentRewrite).filter(SegmentRewrite.segment_id.in_(segment_ids)).all()
        for rewrite in rewrites:
            rewrites_by_segment.setdefault(rewrite.segment_id, []).append(rewrite)

    for segment in segments:
        segment.rewrites = rewrites_by_segment.get(segment.id, [])

    return [_to_segment_response(segment) for segment in segments]


@router.post("/{session_id}/segments/{segment_id}/rewrite", response_model=SegmentShortRewriteResponse | SegmentBulletsRewriteResponse)
def rewrite_session_segment(
    session_id: str,
    segment_id: str,
    payload: SegmentRewriteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SegmentShortRewriteResponse | SegmentBulletsRewriteResponse:
    session = get_owned_session(session_id, current_user, db)
    if not has_segments_tables(db):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=SEGMENTS_UNAVAILABLE)

    try:
        segment_uuid = uuid.UUID(segment_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=SEGMENT_NOT_FOUND)

    segment = (
        db.query(TranscriptSegment)
        .filter(TranscriptSegment.id == segment_uuid, TranscriptSegment.session_id == session.id)
        .first()
    )
    if not segment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=SEGMENT_NOT_FOUND)

    content, model = generate_segment_rewrite(payload.kind, segment.text)

    source_text = " ".join((segment.text or "").split()).strip().lower()
    if payload.kind == "short":
        short_text = " ".join(str(content.get("text", "")).split()).strip()
        if len(short_text) > 220:
            short_text = short_text[:220]
        if len(segment.text.split()) > 8 and short_text.lower() == source_text:
            short_text = short_text[:200].rstrip(" ,.;")
        content = {"text": short_text}
    else:
        raw_bullets = [str(item).strip()[:90] for item in (content.get("bullets") or []) if str(item).strip()]
        bullets: list[str] = []
        seen_normalized: set[str] = set()
        for item in raw_bullets:
            norm = " ".join(item.split()).lower()
            if norm and norm not in seen_normalized:
                bullets.append(item)
                seen_normalized.add(norm)
            if len(bullets) >= 4:
                break
        if len(bullets) < 2 and segment.text.strip():
            fallback_content = rewrite_bullets_fallback(segment.text)
            for item in [str(value).strip()[:90] for value in (fallback_content.get("bullets") or []) if str(value).strip()]:
                norm = " ".join(item.split()).lower()
                if norm and norm not in seen_normalized:
                    bullets.append(item)
                    seen_normalized.add(norm)
                if len(bullets) >= 4:
                    break
        content = {"bullets": bullets[:4]}

    upsert_segment_rewrite(db, segment_id=segment.id, kind=payload.kind, content=content, model=model)
    db.commit()

    if payload.kind == "short":
        return SegmentShortRewriteResponse(kind="short", text=str(content.get("text", "")))
    bullets = [str(item) for item in (content.get("bullets") or [])]
    return SegmentBulletsRewriteResponse(kind="bullets", bullets=bullets)

@router.get("/{session_id}/results", response_model=ResultsResponse)
def get_session_results(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ResultsResponse:
    session = get_owned_session(session_id, current_user, db)
    status_row = db.query(StatusModel).filter(StatusModel.session_id == session.id).first()
    current_status = status_row.status if status_row else "processing"
    if current_status == "queued":
        current_status = "processing"

    normalized = normalize_results_payload(
        session_id=str(session.id),
        session_status=current_status,
        stored_results=session.analysis_results if isinstance(session.analysis_results, dict) else None,
    )
    logger.warning(
        "results response coaching snapshot",
        extra={
            "session_id": str(session.id),
            "status": current_status,
            "questions_items": len((((normalized.get("coaching") or {}).get("questions") or {}).get("items") or [])),
            "summary_items": len((((normalized.get("coaching") or {}).get("summary") or {}).get("bullets") or [])),
        },
    )
    return ResultsResponse(**normalized)
