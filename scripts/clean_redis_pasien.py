import os
from upstash_redis import Redis

redis = Redis(
    url=os.getenv("UPSTASH_REDIS_REST_URL"),
    token=os.getenv("UPSTASH_REDIS_REST_TOKEN")
)

cursor = 0
deleted = 0

while True:
    cursor, keys = redis.scan(cursor, match="pasien:*", count=1000)

    if keys:
        redis.delete(*keys)
        deleted += len(keys)

    if cursor == 0:
        break

print(f"TOTAL KEY PASIEN DIHAPUS: {deleted}")
print("CLEANUP SELESAI")