import os
import json
from upstash_redis import Redis

redis = None

redis_url = os.getenv("UPSTASH_REDIS_REST_URL")
redis_token = os.getenv("UPSTASH_REDIS_REST_TOKEN")

if redis_url and redis_token:
    redis = Redis(
        url=redis_url,
        token=redis_token
    )


def get_cache(key: str):
    if redis is None:
        return None

    try:
        value = redis.get(key)

        if value is None:
            return None

        if isinstance(value, str):
            return json.loads(value)

        return value

    except Exception:
        return None


def set_cache(key: str, value, ttl: int = 3600):
    if redis is None:
        return False

    try:
        redis.set(
            key,
            json.dumps(value, default=str),
            ex=ttl
        )
        return True

    except Exception:
        return False