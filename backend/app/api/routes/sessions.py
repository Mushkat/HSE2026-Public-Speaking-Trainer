import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.models.media import Media as MediaModel
from app.models.session import Session as SessionModel
from app.models.user import User
from app.schemas.session import SessionCreate, SessionResponse
from app.schemas.media import MediaResponse

router = APIRouter(prefix="/sessions", tags=["sessions"])

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


def get_owned_session(session_id: str, current_user: User, db: Session) -> SessionModel:
    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    session = (
        db.query(SessionModel)
        .filter(SessionModel.id == session_uuid, SessionModel.user_id == current_user.id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session


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
    return SessionResponse(id=str(session.id), title=session.title, created_at=session.created_at)


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
    return [SessionResponse(id=str(item.id), title=item.title, created_at=item.created_at) for item in sessions]


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SessionResponse:
    session = get_owned_session(session_id, current_user, db)
    return SessionResponse(id=str(session.id), title=session.title, created_at=session.created_at)


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
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Filename is required")

    original_name = Path(file.filename).name
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Unsupported file type")
    if file.content_type and file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Unsupported file type")

    storage_root = Path(settings.storage_root)
    storage_root_path = storage_root if storage_root.is_absolute() else Path.cwd() / storage_root
    session_dir = storage_root_path / str(session.id)
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
                    raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File too large")
                destination.write(chunk)
    except HTTPException:
        if destination_path.exists():
            destination_path.unlink()
        raise
    finally:
        file.file.close()

    relative_root = storage_root if not storage_root.is_absolute() else Path(storage_root.name)
    relative_path = str(relative_root / str(session.id) / stored_filename)

    media = MediaModel(
        session_id=session.id,
        original_filename=original_name,
        mime_type=file.content_type or "application/octet-stream",
        size_bytes=size_bytes,
        duration_seconds=None,
        storage_path=relative_path,
    )
    db.add(media)
    db.commit()
    db.refresh(media)

    return MediaResponse(
        id=str(media.id),
        session_id=str(media.session_id),
        filename=media.original_filename,
        mime_type=media.mime_type,
        size_bytes=media.size_bytes,
        duration_seconds=media.duration_seconds,
        storage_path=media.storage_path,
        created_at=media.created_at,
    )
