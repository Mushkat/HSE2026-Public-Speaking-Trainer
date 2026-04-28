"""add media preprocess metadata fields

Revision ID: 0005_stage6_media_preprocess
Revises: 0004_single_media_and_cascades
Create Date: 2026-02-22 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_stage6_media_preprocess"
down_revision = "0004_single_media_and_cascades"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("media") as batch_op:
        batch_op.add_column(sa.Column("sample_rate", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("channels", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("processed_audio_path", sa.String(length=500), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("media") as batch_op:
        batch_op.drop_column("processed_audio_path")
        batch_op.drop_column("channels")
        batch_op.drop_column("sample_rate")
