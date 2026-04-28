"""add transcript segments and rewrites

Revision ID: 0006_transcript_segments_rewrites
Revises: 0005_stage6_media_preprocess
Create Date: 2026-03-06 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_transcript_segments_rewrites"
down_revision = "0005_stage6_media_preprocess"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("transcript_segments"):
        op.create_table(
            "transcript_segments",
            sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("session_id", sa.Uuid(as_uuid=True), nullable=False),
            sa.Column("idx", sa.Integer(), nullable=False),
            sa.Column("start_sec", sa.Float(), nullable=False),
            sa.Column("end_sec", sa.Float(), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("word_start_idx", sa.Integer(), nullable=True),
            sa.Column("word_end_idx", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("session_id", "idx", name="uq_transcript_segments_session_idx"),
        )

    transcript_indexes = {idx.get("name") for idx in inspector.get_indexes("transcript_segments")}
    if "ix_transcript_segments_session_id" not in transcript_indexes:
        op.create_index("ix_transcript_segments_session_id", "transcript_segments", ["session_id"])

    if not inspector.has_table("segment_rewrites"):
        op.create_table(
            "segment_rewrites",
            sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("segment_id", sa.Uuid(as_uuid=True), nullable=False),
            sa.Column("kind", sa.String(length=20), nullable=False),
            sa.Column("content", sa.JSON(), nullable=False),
            sa.Column("model", sa.String(length=100), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.ForeignKeyConstraint(["segment_id"], ["transcript_segments.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("segment_id", "kind", name="uq_segment_rewrite_segment_kind"),
        )

    rewrite_indexes = {idx.get("name") for idx in inspector.get_indexes("segment_rewrites")}
    if "ix_segment_rewrites_segment_id" not in rewrite_indexes:
        op.create_index("ix_segment_rewrites_segment_id", "segment_rewrites", ["segment_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("segment_rewrites"):
        rewrite_indexes = {idx.get("name") for idx in inspector.get_indexes("segment_rewrites")}
        if "ix_segment_rewrites_segment_id" in rewrite_indexes:
            op.drop_index("ix_segment_rewrites_segment_id", table_name="segment_rewrites")
        op.drop_table("segment_rewrites")

    if inspector.has_table("transcript_segments"):
        transcript_indexes = {idx.get("name") for idx in inspector.get_indexes("transcript_segments")}
        if "ix_transcript_segments_session_id" in transcript_indexes:
            op.drop_index("ix_transcript_segments_session_id", table_name="transcript_segments")
        op.drop_table("transcript_segments")
