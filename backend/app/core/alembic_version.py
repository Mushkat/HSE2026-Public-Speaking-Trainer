from sqlalchemy import Column, MetaData, PrimaryKeyConstraint, String, Table


def build_wide_alembic_version_table(
    version_table: str = "alembic_version",
    version_table_schema: str | None = None,
    with_primary_key: bool = True,
) -> Table:
    table = Table(
        version_table,
        MetaData(),
        Column("version_num", String(255), nullable=False),
        schema=version_table_schema,
    )
    if with_primary_key:
        table.append_constraint(
            PrimaryKeyConstraint("version_num", name=f"{version_table}_pkc")
        )
    return table
