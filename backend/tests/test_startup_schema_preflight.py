from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ensure_alembic_version.py"
SPEC = spec_from_file_location("ensure_alembic_version", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ensure_runtime_schema_shape = MODULE.ensure_runtime_schema_shape


def test_runtime_schema_preflight_adds_missing_comment_column(tmp_path) -> None:
    db_path = tmp_path / "preflight.db"
    database_url = f"sqlite:///{db_path}"
    engine = create_engine(database_url)

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT,
                    analysis_results TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                "CREATE TABLE alembic_version (version_num VARCHAR(255) NOT NULL PRIMARY KEY)"
            )
        )
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES ('0009_session_comment_text')")
        )

    ensure_runtime_schema_shape(database_url)

    inspector = inspect(engine)
    session_columns = {column["name"] for column in inspector.get_columns("sessions")}
    assert "comment_text" in session_columns


def test_runtime_schema_preflight_skips_comment_column_before_comment_revision(tmp_path) -> None:
    db_path = tmp_path / "preflight_before_comment.db"
    database_url = f"sqlite:///{db_path}"
    engine = create_engine(database_url)

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT,
                    analysis_results TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                "CREATE TABLE alembic_version (version_num VARCHAR(255) NOT NULL PRIMARY KEY)"
            )
        )
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES ('0008_segment_word_idx_not_null')")
        )

    ensure_runtime_schema_shape(database_url)

    inspector = inspect(engine)
    session_columns = {column["name"] for column in inspector.get_columns("sessions")}
    assert "comment_text" not in session_columns


def test_runtime_schema_preflight_does_not_create_alembic_version_table_on_empty_db(tmp_path) -> None:
    db_path = tmp_path / "preflight_empty.db"
    database_url = f"sqlite:///{db_path}"

    ensure_runtime_schema_shape(database_url)

    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert "alembic_version" not in inspector.get_table_names()
