from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, inspect, pool, text

from app.core.alembic_version import build_wide_alembic_version_table

from app.core.config import settings
from app.models.base import Base
from app.models.media import Media
from app.models.session import Session
from app.models.status import Status
from app.models.transcript import Transcript
from app.models.user import User

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def ensure_alembic_version_column(connection) -> None:
    inspector = inspect(connection)

    if "alembic_version" not in inspector.get_table_names():
        return

    if connection.dialect.name.startswith("postgresql"):
        connection.execute(
            text("ALTER TABLE IF EXISTS alembic_version ALTER COLUMN version_num TYPE VARCHAR(255)")
        )
        length = connection.execute(
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
    else:
        version_column = next(
            (column for column in inspector.get_columns("alembic_version") if column.get("name") == "version_num"),
            None,
        )
        if version_column is None:
            raise RuntimeError("alembic_version.version_num column is missing")
        length = getattr(version_column["type"], "length", None)

    if length is None:
        raise RuntimeError("Could not determine alembic_version.version_num length")
    if length < 255:
        raise RuntimeError(f"Failed to widen alembic_version.version_num; current length is {length}")


def override_alembic_version_table() -> None:
    migration_context = context.get_context()
    migration_context._version = build_wide_alembic_version_table(
        version_table=migration_context.version_table,
        version_table_schema=migration_context.version_table_schema,
        with_primary_key=migration_context.opts.get("version_table_pk", True),
    )


def get_url() -> str:
    return settings.database_url


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    override_alembic_version_table()

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        ensure_alembic_version_column(supplied_connection)
        context.configure(connection=supplied_connection, target_metadata=target_metadata)
        override_alembic_version_table()

        with context.begin_transaction():
            context.run_migrations()
        return

    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        ensure_alembic_version_column(connection)
        context.configure(connection=connection, target_metadata=target_metadata)
        override_alembic_version_table()

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
