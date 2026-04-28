import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Uuid

from app.models.base import Base


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    analysis_results: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    comment_text: Mapped[str | None] = mapped_column(String, nullable=True)
    scenario_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="preset")
    scenario_preset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scenario_structured_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    scenario_free_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    scenario_autopick: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scenario_profile_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    scenario_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    scenario_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="sessions")
    media_items = relationship("Media", back_populates="session", cascade="all, delete-orphan", passive_deletes=True)
    status = relationship("Status", back_populates="session", uselist=False, cascade="all, delete-orphan", passive_deletes=True)
    transcript = relationship("Transcript", back_populates="session", uselist=False, cascade="all, delete-orphan", passive_deletes=True)
    transcript_segments = relationship("TranscriptSegment", cascade="all, delete-orphan", passive_deletes=True)
