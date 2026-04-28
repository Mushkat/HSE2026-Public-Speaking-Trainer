import argparse
import os
import sys
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


def mask_url(raw_url: str) -> str:
    try:
        return make_url(raw_url).render_as_string(hide_password=True)
    except Exception:
        return raw_url


def describe_database_url(raw_url: str) -> dict[str, str | int | None]:
    url = make_url(raw_url)
    options = {
        "drivername": url.drivername,
        "username": url.username,
        "host": url.host,
        "port": url.port,
        "database": url.database,
        "query": dict(url.query),
    }
    return options


def print_runtime_db_info(database_url: str) -> None:
    print(f"DATABASE_URL={mask_url(database_url)}")
    details = describe_database_url(database_url)
    print(f"resolved_driver={details['drivername']}")
    print(f"resolved_host={details['host']}")
    print(f"resolved_port={details['port']}")
    print(f"resolved_dbname={details['database']}")
    print(f"resolved_query={details['query']}")


def verify_database(database_url: str) -> int:
    print_runtime_db_info(database_url)
    engine = create_engine(database_url, pool_pre_ping=True)
    with engine.connect() as connection:
        dialect_name = connection.dialect.name
        print(f"dialect={dialect_name}")
        if dialect_name.startswith("postgresql"):
            current_database = connection.execute(text("SELECT current_database()")).scalar()
            current_schema = connection.execute(text("SELECT current_schema()")).scalar()
            users_regclass = connection.execute(text("SELECT to_regclass('public.users')")).scalar()
            alembic_regclass = connection.execute(text("SELECT to_regclass('public.alembic_version')")).scalar()
            alembic_version = None
            if alembic_regclass:
                alembic_version = connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
            print(f"current_database={current_database}")
            print(f"current_schema={current_schema}")
            print(f"public.users={users_regclass}")
            print(f"public.alembic_version={alembic_regclass}")
            print(f"alembic_version={alembic_version}")
            if current_schema != "public":
                print("ERROR: expected current_schema=public", file=sys.stderr)
                return 1
            if not users_regclass:
                print("ERROR: public.users is missing", file=sys.stderr)
                return 1
            if not alembic_regclass or not alembic_version:
                print("ERROR: alembic_version is missing or empty", file=sys.stderr)
                return 1
            return 0

        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        print(f"current_schema=(n/a for {dialect_name})")
        print(f"tables={sorted(tables)}")
        if "users" not in tables or "alembic_version" not in tables:
            print("ERROR: required tables are missing", file=sys.stderr)
            return 1
        alembic_version = connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
        print(f"alembic_version={alembic_version}")
        return 0 if alembic_version else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        print("DATABASE_URL is not set", file=sys.stderr)
        sys.exit(1)

    if args.verify:
        sys.exit(verify_database(database_url))

    print_runtime_db_info(database_url)
