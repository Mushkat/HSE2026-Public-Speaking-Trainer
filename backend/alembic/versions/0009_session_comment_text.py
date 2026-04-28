"""add session comment text

Revision ID: 0009_session_comment_text
Revises: 0008_segment_word_idx_not_null
Create Date: 2026-03-20 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0009_session_comment_text"
down_revision = "0008_segment_word_idx_not_null"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("sessions")}
    if "comment_text" not in columns:
        op.add_column("sessions", sa.Column("comment_text", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("sessions")}
    if "comment_text" in columns:
        op.drop_column("sessions", "comment_text")
