"""make transcript segment word indices required

Revision ID: 0008_segment_word_idx_not_null
Revises: 0007_alembic_ver_len
Create Date: 2026-03-06
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_segment_word_idx_not_null"
down_revision = "0007_alembic_ver_len"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE transcript_segments
        SET word_start_idx = COALESCE(word_start_idx, 0),
            word_end_idx = COALESCE(
                word_end_idx,
                CASE
                    WHEN COALESCE(word_start_idx, 0) > 0 THEN COALESCE(word_start_idx, 0)
                    ELSE 0
                END
            )
        WHERE word_start_idx IS NULL OR word_end_idx IS NULL
    """)
    with op.batch_alter_table("transcript_segments") as batch_op:
        batch_op.alter_column("word_start_idx", existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column("word_end_idx", existing_type=sa.Integer(), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("transcript_segments") as batch_op:
        batch_op.alter_column("word_end_idx", existing_type=sa.Integer(), nullable=True)
        batch_op.alter_column("word_start_idx", existing_type=sa.Integer(), nullable=True)
