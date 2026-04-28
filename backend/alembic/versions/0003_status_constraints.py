"""add status and progress constraints

Revision ID: 0003_status_constraints
Revises: 0002_stage4_status_results
Create Date: 2026-02-14 00:15:00.000000
"""

from alembic import op


revision = "0003_status_constraints"
down_revision = "0002_stage4_status_results"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("statuses") as batch_op:
        batch_op.create_check_constraint(
            "ck_statuses_status_allowed",
            "status IN ('queued', 'processing', 'ready', 'error')",
        )
        batch_op.create_check_constraint(
            "ck_statuses_progress_range",
            "progress IS NULL OR (progress >= 0 AND progress <= 100)",
        )


def downgrade() -> None:
    with op.batch_alter_table("statuses") as batch_op:
        batch_op.drop_constraint("ck_statuses_progress_range", type_="check")
        batch_op.drop_constraint("ck_statuses_status_allowed", type_="check")
