from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.cache import bump_report
from app.common import Id, Writes, Year, get_pendaftaran, next_id, now_ts, require_pegawai
from app.database import get_db

router = APIRouter(prefix="/api/pelayanan", tags=["pelayanan"])


class PenangananRujukan(BaseModel):
    no_registrasi: Id
    id_pegawai: Id
    id_pegawai_peminta: Id
    versi_harga: Year = "2026"


@router.post("/penanganan-rujukan", status_code=201)
def penanganan_rujukan(body: PenangananRujukan, db=Depends(get_db)):
    get_pendaftaran(db, body.no_registrasi)
    require_pegawai(db, body.id_pegawai, body.id_pegawai_peminta)

    layanan = {l["id_layanan"]: l for l in db.layanan.find({"kategori": "Pemeriksaan"}, {"_id": 0})}
    offered = sorted(
        (p for p in db.penyediaan_layanan.find({}, {"_id": 0}) if p["id_layanan"] in layanan
         and any(t["versi_harga"] == body.versi_harga for t in layanan[p["id_layanan"]].get("tarif", []))),
        key=lambda p: (int(p["id_unit"]), int(p["id_layanan"]))
    )

    if not offered:
        raise HTTPException(status_code=409, detail="tidak ada layanan pemeriksaan dengan tarif versi ini")

    chosen = offered[0]
    id_pelayanan = next_id(db, "pelayanan_medis")
    selesai = (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S.%f")
    writes = Writes(db)

    try:
        writes.insert("pelayanan_medis", {
            "id_pelayanan_medis": id_pelayanan,
            "waktu_mulai": now_ts(),
            "waktu_selesai": selesai,
            "no_registrasi": body.no_registrasi,
            "id_layanan": chosen["id_layanan"],
            "versi_harga": body.versi_harga,
            "id_unit": chosen["id_unit"],
        })
        writes.insert("penanganan_medis", {
            "id_pelayanan_medis": id_pelayanan,
            "id_pegawai": body.id_pegawai,
            "id_pegawai_peminta": body.id_pegawai_peminta,
            "id_jadwal": None,
        })

    except Exception:
        writes.rollback()
        raise HTTPException(status_code=503, detail="gagal menyimpan penanganan")

    bump_report("layanan-terpopuler", "klaim")

    return {"id_pelayanan_medis": id_pelayanan, "id_layanan": chosen["id_layanan"], "waktu_selesai": selesai}
