from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import HTTPException
from pydantic import Field, StringConstraints
from pymongo import ReturnDocument

from app.cache import get_cache, set_cache

NO_NUL = r"^[^\x00]*$"

Nik = Annotated[str, Field(pattern=r"^[0-9]{16}$")]
Id = Annotated[str, Field(pattern=r"^[0-9]{1,12}$")]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200, pattern=NO_NUL)]
Year = Annotated[str, Field(pattern=r"^[0-9]{4}$")]
Time = Annotated[str, Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9](:[0-5][0-9])?$")]
Detail = Annotated[
    dict[Annotated[str, Field(max_length=50)], Annotated[str, Field(max_length=200)] | int | float | None],
    Field(max_length=10)
]

DAYS = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]


def now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


def today() -> str:
    return date.today().isoformat()


def next_day(tanggal: str) -> str:
    return (date.fromisoformat(tanggal) + timedelta(days=1)).isoformat()


def parse_date(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail="tanggal tidak valid, pakai format YYYY-MM-DD")

    if not 2000 <= parsed.year <= 2100:
        raise HTTPException(status_code=422, detail="tahun harus antara 2000 dan 2100")

    return parsed.isoformat()


def chunked_find(collection, field, values, extra=None, projection=None):
    values = list(values)
    projection = projection if projection is not None else {"_id": 0}

    for i in range(0, len(values), 1000):
        query = {field: {"$in": values[i:i + 1000]}}

        if extra:
            query.update(extra)

        yield from collection.find(query, projection)


def money(value) -> Decimal:
    return Decimal(str(value))


def get_pendaftaran(db, no_registrasi: str) -> dict:
    doc = db.pendaftaran.find_one({"no_registrasi": no_registrasi}, {"_id": 0})

    if doc is None:
        raise HTTPException(status_code=404, detail="pendaftaran tidak ditemukan")

    return doc


def penjamin_umum(db) -> dict:
    doc = db.penjamin.find_one({"nama_penjamin": "Umum / Mandiri"}, {"_id": 0})

    if doc is None:
        raise HTTPException(status_code=500, detail="penjamin 'Umum / Mandiri' tidak ada di database")

    return doc


class Writes:
    def __init__(self, db):
        self.db = db
        self.done = []

    def insert(self, collection: str, doc: dict):
        result = self.db[collection].insert_one(doc)
        self.done.append((collection, result.inserted_id))

    def rollback(self):
        for collection, _id in reversed(self.done):
            self.db[collection].delete_one({"_id": _id})

        self.done = []


ID_SOURCES = {
    "rme": ("rme", "no_rm"),
    "pendaftaran": ("pendaftaran", "no_registrasi"),
    "pelayanan_medis": ("pelayanan_medis", "id_pelayanan_medis"),
    "pembayaran": ("pembayaran", "no_billing"),
}


def highest_existing_id(db, name: str) -> int:
    if name == "klaim_asuransi":
        docs = db.pendaftaran.find({"klaim_asuransi": {"$ne": []}}, {"_id": 0, "klaim_asuransi": 1})
        values = (int(k["id_asuransi"]) for d in docs for k in d.get("klaim_asuransi") or [])
    else:
        collection, field = ID_SOURCES[name]
        docs = db[collection].find({}, {"_id": 0, field: 1})
        values = (int(d[field]) for d in docs if d.get(field) is not None)

    return max(values, default=0)


def next_id(db, name: str) -> str:
    if db.counters.find_one({"_id": name}) is None:
        db.counters.update_one(
            {"_id": name},
            {"$setOnInsert": {"seq": highest_existing_id(db, name)}},
            upsert=True
        )

    doc = db.counters.find_one_and_update(
        {"_id": name},
        {"$inc": {"seq": 1}},
        return_document=ReturnDocument.AFTER
    )

    return str(doc["seq"])


def get_master(db, name: str, key: str) -> dict:
    cache_key = f"simrs:master:{name}"
    rows = get_cache(cache_key)

    if rows is None:
        rows = list(db[name].find({}, {"_id": 0}))
        set_cache(cache_key, rows, ttl=3600)

    return {row[key]: row for row in rows}


def require_pegawai(db, *ids):
    pegawai = get_master(db, "pegawai", "id_pegawai")

    if any(i not in pegawai for i in ids):
        raise HTTPException(status_code=404, detail="pegawai tidak ditemukan")


def visit_counts(db, tanggal: str, id_jadwal: str | None = None) -> dict:
    services = {
        d["id_pelayanan_medis"]: d["no_registrasi"]
        for d in db.pelayanan_medis.find(
            {"waktu_mulai": {"$gte": tanggal, "$lt": next_day(tanggal)}},
            {"_id": 0, "id_pelayanan_medis": 1, "no_registrasi": 1}
        )
    }
    schedule = {"id_jadwal": id_jadwal} if id_jadwal else {"id_jadwal": {"$ne": None}}
    handled = list(chunked_find(db.penanganan_medis, "id_pelayanan_medis", services, extra=schedule))
    outpatient = {d["no_registrasi"] for d in
                  chunked_find(db.rawat_jalan, "no_registrasi", {services[h["id_pelayanan_medis"]] for h in handled})}

    visits = {}
    for h in handled:
        reg = services[h["id_pelayanan_medis"]]

        if reg in outpatient:
            visits.setdefault(h["id_jadwal"], set()).add(reg)

    return {jadwal: len(regs) for jadwal, regs in visits.items()}
