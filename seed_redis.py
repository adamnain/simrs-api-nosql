
import os
import json
from pymongo import MongoClient
from upstash_redis import Redis

print("MULAI SEED REDIS...", flush=True)

mongo = MongoClient(os.getenv("MONGODB_URL"))
db = mongo["simrs"]

redis = Redis(
    url=os.getenv("UPSTASH_REDIS_REST_URL"),
    token=os.getenv("UPSTASH_REDIS_REST_TOKEN")
)

TTL = 3600


def simpan(key, data):
    redis.set(
        key,
        json.dumps(data, default=str),
        ex=TTL
    )
    print("TERSIMPAN:", key, flush=True)


def seed_master(collection, key_field, prefix):
    jumlah = 0

    for doc in db[collection].find({}, {"_id": 0}):
        value = doc.get(key_field)

        if value is not None:
            simpan(f"{prefix}:{value}", doc)
            jumlah += 1

    print(f"TOTAL {collection}: {jumlah}", flush=True)


if __name__ == "__main__":
    seed_master("pegawai", "id_pegawai", "pegawai")
    seed_master("penjamin", "id_penjamin", "penjamin")
    seed_master("unit_layanan", "id_unit", "unit")
    seed_master("layanan", "id_layanan", "layanan")
    seed_master("kelas_ruangan", "id_kelas", "kelas_ruangan")
    seed_master("obat", "no_obat", "obat")

    print("SELESAI MENGISI REDIS!", flush=True)
    mongo.close()
