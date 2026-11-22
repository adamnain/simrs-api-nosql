from fastapi import APIRouter, Depends

from app.cache import cached_master
from app.database import get_db

router = APIRouter(prefix="/api/master", tags=["master"])

DAY = 86400
HOUR = 3600


def kelas_ruangan(db):
    def compute():
        return sorted(db.kelas_ruangan.find({}, {"_id": 0}), key=lambda r: int(r["id_kelas"]))

    return cached_master("kelas_ruangan", compute, ttl=DAY)


def tarif_kelas(db):
    def compute():
        return sorted(db.tarif_kelas.find({}, {"_id": 0}), key=lambda r: (int(r["id_kelas"]), r["versi_harga"]))

    return cached_master("tarif_kelas", compute, ttl=DAY)


def unit_layanan(db):
    def compute():
        return sorted(db.unit_layanan.find({}, {"_id": 0}), key=lambda r: int(r["id_unit"]))

    return cached_master("unit_layanan", compute, ttl=DAY)


def penjamin(db):
    def compute():
        return sorted(db.penjamin.find({}, {"_id": 0}), key=lambda r: int(r["id_penjamin"]))

    return cached_master("penjamin", compute, ttl=DAY)


def layanan(db):
    def compute():
        return sorted(db.layanan.find({}, {"_id": 0}), key=lambda r: int(r["id_layanan"]))

    return cached_master("layanan", compute, ttl=DAY)


def obat(db):
    def compute():
        return sorted(db.obat.find({}, {"_id": 0}), key=lambda r: int(r["no_obat"]))

    return cached_master("obat", compute, ttl=DAY)


def ruangan(db):
    def compute():
        return sorted(db.ruangan.find({}, {"_id": 0, "status_ruangan": 0}), key=lambda r: int(r["id_ruangan"]))

    return cached_master("ruangan", compute, ttl=DAY)


def jadwal_dokter(db):
    def compute():
        return sorted(db.jadwal_dokter.find({}, {"_id": 0}), key=lambda r: int(r["id_jadwal"]))

    return cached_master("jadwal_dokter", compute, ttl=DAY)


@router.get("/kelas-ruangan")
def list_kelas_ruangan(db=Depends(get_db)):
    return kelas_ruangan(db)


@router.get("/tarif-kelas")
def list_tarif_kelas(db=Depends(get_db)):
    return tarif_kelas(db)


@router.get("/unit-layanan")
def list_unit_layanan(db=Depends(get_db)):
    return unit_layanan(db)


@router.get("/penjamin")
def list_penjamin(db=Depends(get_db)):
    return penjamin(db)


@router.get("/layanan")
def list_layanan(db=Depends(get_db)):
    return layanan(db)


@router.get("/obat")
def list_obat(db=Depends(get_db)):
    return obat(db)


@router.get("/ruangan")
def list_ruangan(db=Depends(get_db)):
    return ruangan(db)


@router.get("/jadwal-dokter")
def list_jadwal_dokter(db=Depends(get_db)):
    return jadwal_dokter(db)
