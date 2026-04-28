from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ensure_alembic_version.py"
SPEC = spec_from_file_location("ensure_alembic_version", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class FakeInspector:
    def __init__(self):
        self.columns_calls = 0

    def get_table_names(self):
        return ["alembic_version"]

    def get_columns(self, _table_name):
        self.columns_calls += 1
        return [{"name": "version_num", "type": type("Type", (), {"length": 32})()}]


class FakeConnection:
    def __init__(self, length):
        self.dialect = type("Dialect", (), {"name": "postgresql"})()
        self.length = length
        self.calls = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append(sql)
        if "ALTER TABLE IF EXISTS alembic_version ALTER COLUMN version_num TYPE VARCHAR(255)" in sql:
            self.length = 255
            return FakeResult(None)
        if "information_schema.columns" in sql:
            return FakeResult(self.length)
        return FakeResult(None)


def test_ensure_alembic_version_shape_widens_postgres_varchar_32(monkeypatch) -> None:
    fake_inspector = FakeInspector()
    fake_connection = FakeConnection(32)
    monkeypatch.setattr(MODULE, "inspect", lambda _connection: fake_inspector)

    MODULE.ensure_alembic_version_shape(fake_connection)

    assert any("information_schema.columns" in sql for sql in fake_connection.calls)
    assert any("ALTER TABLE IF EXISTS alembic_version ALTER COLUMN version_num TYPE VARCHAR(255)" in sql for sql in fake_connection.calls)
    assert fake_inspector.columns_calls == 0
