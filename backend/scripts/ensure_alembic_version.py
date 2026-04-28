import os

from sqlalchemy import create_engine, inspect, text

DATABASE_URL = os.getenv("DATABASE_URL", "")
TARGET_LENGTH = 255
COMMENT_REVISION_NUMBER = 9


def get_alembic_version_length(connection) -> int | None:
    if connection.dialect.name.startswith("postgresql"):
        return connection.execute(
            text(
                """
                SELECT character_maximum_length
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'alembic_version'
                  AND column_name = 'version_num'
                """
            )
        ).scalar()

    inspector = inspect(connection)
    version_column = next(
        (column for column in inspector.get_columns("alembic_version") if column.get("name") == "version_num"),
        None,
    )
    if version_column is None:
        raise RuntimeError("alembic_version.version_num column is missing")
    return getattr(version_column["type"], "length", None)


def ensure_alembic_version_shape(connection) -> None:
    inspector = inspect(connection)
    table_names = inspector.get_table_names()
    if "alembic_version" not in table_names:
        print("alembic_version table is absent; leaving creation to Alembic")
        return

    if connection.dialect.name.startswith("postgresql"):
        connection.execute(
            text("ALTER TABLE IF EXISTS alembic_version ALTER COLUMN version_num TYPE VARCHAR(255)")
        )

    version_length = get_alembic_version_length(connection)
    if version_length is None:
        raise RuntimeError("Could not determine alembic_version.version_num length")

    if version_length < TARGET_LENGTH:
        raise RuntimeError(
            f"Failed to widen alembic_version.version_num; current length is {version_length}"
        )

    print(f"alembic_version.version_num ready: VARCHAR({version_length})")


def get_current_revision(connection) -> str | None:
    inspector = inspect(connection)
    if "alembic_version" not in inspector.get_table_names():
        return None

    row = connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
    return str(row) if row else None


def revision_number(version: str | None) -> int | None:
    if not version:
        return None

    prefix = version.split("_", 1)[0]
    if not prefix.isdigit():
        return None
    return int(prefix)


def ensure_sessions_comment_column(connection) -> None:
    inspector = inspect(connection)
    table_names = inspector.get_table_names()
    if "sessions" not in table_names:
        print("sessions table not found; skipping comment_text preflight")
        return

    current_revision = get_current_revision(connection)
    current_revision_number = revision_number(current_revision)
    if current_revision_number is None or current_revision_number < COMMENT_REVISION_NUMBER:
        print(f"sessions.comment_text not expected at revision {current_revision}; skipping")
        return

    session_columns = {column["name"] for column in inspector.get_columns("sessions")}
    if "comment_text" in session_columns:
        print("sessions.comment_text already present")
        return

    connection.execute(text("ALTER TABLE sessions ADD COLUMN comment_text TEXT"))
    print("Added missing sessions.comment_text column")


def ensure_runtime_schema_shape(database_url: str | None = None) -> None:
    resolved_database_url = database_url or DATABASE_URL
    if not resolved_database_url:
        print("DATABASE_URL is not set; skipping alembic_version preflight")
        return

    engine = create_engine(resolved_database_url)
    with engine.begin() as connection:
        ensure_alembic_version_shape(connection)
        ensure_sessions_comment_column(connection)


if __name__ == "__main__":
    ensure_runtime_schema_shape()
