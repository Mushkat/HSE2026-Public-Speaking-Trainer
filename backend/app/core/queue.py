from app.core.config import settings


def get_redis_connection():
    from redis import Redis

    return Redis.from_url(settings.redis_url)


def get_analysis_queue():
    from rq import Queue

    return Queue("analysis", connection=get_redis_connection())
