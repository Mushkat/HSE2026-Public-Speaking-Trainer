import os
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL", "")
MIGRATION_LOCK_ID = 904202603451
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI_PATH = PROJECT_ROOT / "alembic.ini"
ALEMBIC_SCRIPT_PATH = PROJECT_ROOT / "alembic"
ENSURE_SCRIPT_PATH = Path(__file__).resolve().with_name("ensure_alembic_version.py")
ENSURE_SPEC = spec_from_file_location("ensure_alembic_version", ENSURE_SCRIPT_PATH)
assert ENSURE_SPEC is not None and ENSURE_SPEC.loader is not None
ENSURE_MODULE = module_from_spec(ENSURE_SPEC)
ENSURE_SPEC.loader.exec_module(ENSURE_MODULE)
ensure_alembic_version_shape = ENSURE_MODULE.ensure_alembic_version_shape
ensure_sessions_comment_column = ENSURE_MODULE.ensure_sessions_comment_column


def build_alembic_config(connection=None) -> Config:
    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(ALEMBIC_SCRIPT_PATH))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def run_alembic_upgrade(connection=None) -> None:
    command.upgrade(build_alembic_config(connection), "head")


def finalize_connection_after_upgrade(connection) -> None:
    if connection.in_transaction():
        connection.commit()


def run_migrations_with_lock(database_url: str | None = None) -> None:
    resolved_database_url = database_url or DATABASE_URL
    if not resolved_database_url:
        run_alembic_upgrade()
        return

    engine = create_engine(resolved_database_url)
    with engine.connect() as connection:
        if connection.dialect.name.startswith("postgresql"):
            connection.execute(text("SELECT pg_advisory_lock(:lock_id)"), {"lock_id": MIGRATION_LOCK_ID})
            connection.commit()
            try:
                with connection.begin():
                    ensure_alembic_version_shape(connection)
                run_alembic_upgrade(connection)
                finalize_connection_after_upgrade(connection)
                with connection.begin():
                    ensure_sessions_comment_column(connection)
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": MIGRATION_LOCK_ID})
                connection.commit()
        else:
            with connection.begin():
                ensure_alembic_version_shape(connection)
            run_alembic_upgrade(connection)
            finalize_connection_after_upgrade(connection)
            with connection.begin():
                ensure_sessions_comment_column(connection)


if __name__ == "__main__":
    run_migrations_with_lock()
