"""add scenario v1 fields to sessions

Revision ID: 0010_session_scenario_fields
Revises: 0009_session_comment_text
Create Date: 2026-04-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "0010_session_scenario_fields"
down_revision = "0009_session_comment_text"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("sessions")}

    if "scenario_mode" not in columns:
        op.add_column("sessions", sa.Column("scenario_mode", sa.String(length=32), nullable=False, server_default="preset"))
    if "scenario_preset_id" not in columns:
        op.add_column("sessions", sa.Column("scenario_preset_id", sa.String(length=64), nullable=True))
    if "scenario_structured_json" not in columns:
        op.add_column("sessions", sa.Column("scenario_structured_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    if "scenario_free_text" not in columns:
        op.add_column("sessions", sa.Column("scenario_free_text", sa.Text(), nullable=True))
    if "scenario_autopick" not in columns:
        op.add_column("sessions", sa.Column("scenario_autopick", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "scenario_profile_json" not in columns:
        op.add_column("sessions", sa.Column("scenario_profile_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    if "scenario_version" not in columns:
        op.add_column("sessions", sa.Column("scenario_version", sa.Integer(), nullable=False, server_default="1"))
    if "scenario_updated_at" not in columns:
        op.add_column("sessions", sa.Column("scenario_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("sessions")}

    for name in [
        "scenario_updated_at",
        "scenario_version",
        "scenario_profile_json",
        "scenario_autopick",
        "scenario_free_text",
        "scenario_structured_json",
        "scenario_preset_id",
        "scenario_mode",
    ]:
        if name in columns:
            op.drop_column("sessions", name)
