import os
from pymongo import MongoClient

MONGODB_URL = os.getenv("MONGODB_URL")

client = MongoClient(
    MONGODB_URL,
    serverSelectionTimeoutMS=5000
)

db = client["simrs"]


def check_mongodb():
    client.admin.command("ping")
    return True


def get_db():
    return db


INDEXES = {
    "pasien": ["no_rm"],
    "pendaftaran": ["no_registrasi", "nik_pasien"],
    "pelayanan_medis": ["id_pelayanan_medis", "no_registrasi", "waktu_mulai"],
    "penunjang_medis": ["id_pelayanan_medis", "tanggal_permintaan"],
    "penanganan_medis": ["id_pelayanan_medis"],
    "operasi": ["id_pelayanan_medis"],
    "perawatan_klinis": ["id_pelayanan_medis"],
    "diagnosis": ["id_pelayanan_medis"],
    "entri_pendaftaran": ["no_registrasi"],
    "entri_pelayanan": ["id_pelayanan_medis"],
    "entri_rme": ["id_entri"],
    "pembayaran": ["no_billing", "no_registrasi", "tanggal_pembayaran"],
    "penempatan_ruangan": ["id_ruangan"],
    "daftar_penjaminan": ["nik_pasien"],
    "rawat_jalan": ["no_registrasi"],
    "igd": ["no_registrasi"],
    "admisi": ["no_registrasi"],
}


def ensure_indexes():
    for collection, fields in INDEXES.items():
        for field in fields:
            db[collection].create_index(field)

    db.pasien.create_index("nik_pasien", unique=True)
