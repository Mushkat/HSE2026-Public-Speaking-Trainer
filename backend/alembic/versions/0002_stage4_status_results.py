"""stage4 status unique and analysis results

Revision ID: 0002_stage4_status_results
Revises: 0001_initial
Create Date: 2026-02-14 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_stage4_status_results"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("analysis_results", sa.JSON(), nullable=True))
    op.create_index("ix_statuses_session_id_unique", "statuses", ["session_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_statuses_session_id_unique", table_name="statuses")
    op.drop_column("sessions", "analysis_results")
