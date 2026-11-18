
import os
import json
from pymongo import MongoClient
from upstash_redis import Redis
from bson import json_util

# MongoDB
mongo = MongoClient(os.getenv("MONGODB_URL"))
db = mongo["simrs"]

# Upstash Redis
redis = Redis(
    url=os.getenv("UPSTASH_REDIS_REST_URL"),
    token=os.getenv("UPSTASH_REDIS_REST_TOKEN")
)

TTL = 3600

# Collection dan field untuk Redis key
CONFIG = {
    "pegawai": ("pegawai", "id_pegawai"),
    "penjamin": ("penjamin", "id_penjamin"),
    "unit": ("unit_layanan", "id_unit"),
    "layanan": ("layanan", "id_layanan"),
    "kelas_ruangan": ("kelas_ruangan", "id_kelas"),
    "obat": ("obat", "no_obat"),
}

total = 0

for prefix, (collection, field) in CONFIG.items():
    print(f"Importing {collection}...")

    cursor = db[collection].find({})

    for document in cursor:
        value = document.get(field)

        if value is None:
            continue

        key = f"{prefix}:{value}"

        data = json.loads(json_util.dumps(document))

        redis.set(key, json.dumps(data), ex=TTL)

        total += 1

    print(f"{collection} completed")

print(f"TOTAL REDIS KEYS: {total}")
print("REDIS SEEDING COMPLETED")
