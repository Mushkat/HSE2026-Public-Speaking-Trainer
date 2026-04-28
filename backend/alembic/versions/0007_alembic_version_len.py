"""widen alembic version column length

Revision ID: 0007_alembic_ver_len
Revises: 0006_transcript_segments_rewrites
Create Date: 2026-03-06 01:00:00.000000
"""

from alembic import op


revision = "0007_alembic_ver_len"
down_revision = "0006_transcript_segments_rewrites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(255)")


def downgrade() -> None:
    pass
