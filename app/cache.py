import os
import json

redis = None

redis_url = os.getenv("UPSTASH_REDIS_REST_URL")
redis_token = os.getenv("UPSTASH_REDIS_REST_TOKEN")

if redis_url and redis_token:
    from upstash_redis import Redis

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


def report_version(name: str) -> int:
    if redis is None:
        return 0

    try:
        return int(redis.get(f"simrs:report:{name}:ver") or 0)

    except Exception:
        return 0


def bump_report(*names: str):
    if redis is None:
        return

    for name in names:
        try:
            redis.incr(f"simrs:report:{name}:ver")
        except Exception:
            pass


def cached(key: str, compute, ttl: int = 3600) -> tuple:
    """Return (data, source): from Redis when cached, otherwise compute() from MongoDB and store it."""
    hit = get_cache(key)

    if hit is not None:
        return hit, "redis"

    data = compute()
    set_cache(key, data, ttl=ttl)

    return data, "mongodb"


def cached_report(name: str, params: str, compute, ttl: int = 600):
    key = f"simrs:report:{name}:v{report_version(name)}:{params}"
    data, source = cached(key, compute, ttl=ttl)

    return {"source": source, "data": data}


def cached_master(collection: str, compute, ttl: int = 3600) -> dict:
    key = f"simrs:master:{collection}"
    rows, source = cached(key, compute, ttl=ttl)

    return {"metadata": {"source": source, "collection": collection, "total": len(rows)}, "data": rows}
