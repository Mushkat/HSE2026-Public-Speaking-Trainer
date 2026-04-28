"""enforce one media per session and cascade deletes

Revision ID: 0004_single_media_and_cascades
Revises: 0003_status_constraints
Create Date: 2026-02-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_single_media_and_cascades"
down_revision = "0003_status_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    duplicate_session_ids = [
        row[0]
        for row in conn.execute(
            sa.text(
                """
                SELECT session_id
                FROM media
                GROUP BY session_id
                HAVING COUNT(*) > 1
                """
            )
        )
    ]

    for session_id in duplicate_session_ids:
        rows = conn.execute(
            sa.text(
                """
                SELECT id
                FROM media
                WHERE session_id = :session_id
                ORDER BY created_at DESC, id DESC
                """
            ),
            {"session_id": session_id},
        ).fetchall()
        for media_id, in rows[1:]:
            conn.execute(sa.text("DELETE FROM media WHERE id = :media_id"), {"media_id": media_id})

    with op.batch_alter_table("media") as batch_op:
        batch_op.create_unique_constraint("uq_media_session_id", ["session_id"])

    # On PostgreSQL, recreate FKs with ON DELETE CASCADE.
    if conn.dialect.name == "postgresql":
        op.execute("ALTER TABLE media DROP CONSTRAINT IF EXISTS media_session_id_fkey")
        op.execute(
            "ALTER TABLE media ADD CONSTRAINT media_session_id_fkey FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE"
        )
        op.execute("ALTER TABLE statuses DROP CONSTRAINT IF EXISTS statuses_session_id_fkey")
        op.execute(
            "ALTER TABLE statuses ADD CONSTRAINT statuses_session_id_fkey FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE"
        )
        op.execute("ALTER TABLE transcripts DROP CONSTRAINT IF EXISTS transcripts_session_id_fkey")
        op.execute(
            "ALTER TABLE transcripts ADD CONSTRAINT transcripts_session_id_fkey FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE"
        )


def downgrade() -> None:
    conn = op.get_bind()

    if conn.dialect.name == "postgresql":
        op.execute("ALTER TABLE transcripts DROP CONSTRAINT IF EXISTS transcripts_session_id_fkey")
        op.execute(
            "ALTER TABLE transcripts ADD CONSTRAINT transcripts_session_id_fkey FOREIGN KEY (session_id) REFERENCES sessions(id)"
        )
        op.execute("ALTER TABLE statuses DROP CONSTRAINT IF EXISTS statuses_session_id_fkey")
        op.execute(
            "ALTER TABLE statuses ADD CONSTRAINT statuses_session_id_fkey FOREIGN KEY (session_id) REFERENCES sessions(id)"
        )
        op.execute("ALTER TABLE media DROP CONSTRAINT IF EXISTS media_session_id_fkey")
        op.execute("ALTER TABLE media ADD CONSTRAINT media_session_id_fkey FOREIGN KEY (session_id) REFERENCES sessions(id)")

    with op.batch_alter_table("media") as batch_op:
        batch_op.drop_constraint("uq_media_session_id", type_="unique")
