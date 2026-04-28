from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic.config import Config


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_migrations.py"
SPEC = spec_from_file_location("run_migrations", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeConnection:
    def __init__(self, dialect_name: str):
        self.dialect = type("Dialect", (), {"name": dialect_name})()
        self.calls: list[tuple[str, dict[str, int]]] = []
        self._in_transaction = False

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        sql = str(statement)
        if "SELECT version_num FROM alembic_version" in sql:
            return type("Result", (), {"scalar": lambda self: "0009_session_comment_text"})()

    def begin(self):
        self._in_transaction = True
        return self

    def commit(self):
        self._in_transaction = False
        self.calls.append(("commit", {}))

    def in_transaction(self):
        return self._in_transaction

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeEngine:
    def __init__(self, connection: FakeConnection):
        self.connection = connection

    def connect(self):
        return self.connection


def test_run_migrations_with_lock_for_postgres(monkeypatch) -> None:
    fake_connection = FakeConnection("postgresql")
    monkeypatch.setattr(MODULE, "create_engine", lambda _url: FakeEngine(fake_connection))
    alembic_calls: list[str] = []
    monkeypatch.setattr(MODULE, "run_alembic_upgrade", lambda _connection=None: (alembic_calls.append("upgrade"), setattr(fake_connection, "_in_transaction", True)))
    monkeypatch.setattr(MODULE, "ensure_alembic_version_shape", lambda _connection: fake_connection.calls.append(("ensure_alembic_version_shape", {})))
    monkeypatch.setattr(MODULE, "ensure_sessions_comment_column", lambda _connection: fake_connection.calls.append(("ensure_sessions_comment_column", {})))

    MODULE.run_migrations_with_lock("postgresql+psycopg2://example")

    assert alembic_calls == ["upgrade"]
    assert fake_connection.calls == [
        ("SELECT pg_advisory_lock(:lock_id)", {"lock_id": MODULE.MIGRATION_LOCK_ID}),
        ("commit", {}),
        ("ensure_alembic_version_shape", {}),
        ("commit", {}),
        ("ensure_sessions_comment_column", {}),
        ("SELECT pg_advisory_unlock(:lock_id)", {"lock_id": MODULE.MIGRATION_LOCK_ID}),
        ("commit", {}),
    ]


def test_run_migrations_without_lock_for_sqlite(monkeypatch) -> None:
    fake_connection = FakeConnection("sqlite")
    monkeypatch.setattr(MODULE, "create_engine", lambda _url: FakeEngine(fake_connection))
    alembic_calls: list[str] = []
    monkeypatch.setattr(MODULE, "run_alembic_upgrade", lambda _connection=None: (alembic_calls.append("upgrade"), setattr(fake_connection, "_in_transaction", True)))
    monkeypatch.setattr(MODULE, "ensure_alembic_version_shape", lambda _connection: fake_connection.calls.append(("ensure_alembic_version_shape", {})))
    monkeypatch.setattr(MODULE, "ensure_sessions_comment_column", lambda _connection: fake_connection.calls.append(("ensure_sessions_comment_column", {})))

    MODULE.run_migrations_with_lock("sqlite:///tmp.db")

    assert alembic_calls == ["upgrade"]
    assert fake_connection.calls == [
        ("ensure_alembic_version_shape", {}),
        ("commit", {}),
        ("ensure_sessions_comment_column", {}),
    ]


def test_build_alembic_config_binds_connection() -> None:
    fake_connection = object()

    config = MODULE.build_alembic_config(fake_connection)

    assert isinstance(config, Config)
    assert config.attributes["connection"] is fake_connection
    assert config.get_main_option("script_location").endswith("backend/alembic")


def test_finalize_connection_after_upgrade_commits_active_transaction() -> None:
    fake_connection = FakeConnection("postgresql")
    fake_connection._in_transaction = True

    MODULE.finalize_connection_after_upgrade(fake_connection)

    assert fake_connection.calls == [("commit", {})]
    assert fake_connection.in_transaction() is False
