from app.core.alembic_version import build_wide_alembic_version_table


def test_build_wide_alembic_version_table_uses_varchar_255() -> None:
    table = build_wide_alembic_version_table()

    assert table.name == "alembic_version"
    assert table.c.version_num.type.length == 255
    assert table.primary_key is not None


def test_build_wide_alembic_version_table_can_disable_primary_key() -> None:
    table = build_wide_alembic_version_table(with_primary_key=False)

    assert table.c.version_num.type.length == 255
    assert len(table.primary_key.columns) == 0
