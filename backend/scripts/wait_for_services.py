import os
import time

import redis
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL", "")
REDIS_URL = os.getenv("REDIS_URL", "")
MAX_RETRIES = int(os.getenv("STARTUP_MAX_RETRIES", "60"))
SLEEP_SECONDS = float(os.getenv("STARTUP_SLEEP_SECONDS", "2"))


def wait_for_database() -> None:
    engine = create_engine(DATABASE_URL)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            print("Database is ready")
            return
        except Exception as exc:
            print(f"[{attempt}/{MAX_RETRIES}] Waiting for database: {exc}")
            time.sleep(SLEEP_SECONDS)
    raise RuntimeError("Database did not become ready in time")


def wait_for_redis() -> None:
    client = redis.from_url(REDIS_URL)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            client.ping()
            print("Redis is ready")
            return
        except Exception as exc:
            print(f"[{attempt}/{MAX_RETRIES}] Waiting for redis: {exc}")
            time.sleep(SLEEP_SECONDS)
    raise RuntimeError("Redis did not become ready in time")


if __name__ == "__main__":
    if DATABASE_URL:
        wait_for_database()
    if REDIS_URL:
        wait_for_redis()
