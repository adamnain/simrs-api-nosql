import re
from collections import Counter
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from app.common import (NO_NUL, Id, Nik, Text, Writes, chunked_find, get_master, next_id, penjamin_umum,
                        require_pegawai)
from app.database import get_db

router = APIRouter(prefix="/api/pasien", tags=["pasien"])


class PasienBaru(BaseModel):
    nik_pasien: Nik
    nama_pasien: Text
    tanggal_lahir_pasien: str
    jenis_kelamin: Literal["L", "P"]
    jalan: Text
    rt: Annotated[str, Field(pattern=r"^[0-9]{1,3}$")]
    rw: Annotated[str, Field(pattern=r"^[0-9]{1,3}$")]
    kota: Text
    provinsi: Text
    no_telp_pasien: Annotated[str, Field(pattern=r"^[0-9+\-]{6,20}$")]
    id_pegawai: Id

    @field_validator("tanggal_lahir_pasien")
    @classmethod
    def valid_birth_date(cls, value):
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            raise ValueError("pakai format YYYY-MM-DD")

        if not date(1900, 1, 1) <= parsed <= date.today():
            raise ValueError("tanggal lahir di luar rentang")

        return parsed.isoformat()


@router.get("")
def cari_pasien(nik: Annotated[str | None, Query(max_length=100, pattern=NO_NUL)] = None,
                nama: Annotated[str | None, Query(max_length=100, pattern=NO_NUL)] = None, db=Depends(get_db)):
    conditions = []

    if nik:
        conditions.append({"nik_pasien": nik})

    if nama:
        conditions.append({"nama_pasien": {"$regex": re.escape(nama), "$options": "i"}})

    if not conditions:
        raise HTTPException(status_code=422, detail="isi nik atau nama")

    pasien = list(db.pasien.find({"$or": conditions}, {"_id": 0}).limit(50))
    penjamin = get_master(db, "penjamin", "id_penjamin")

    guarantors = {}
    for dp in chunked_find(db.daftar_penjaminan, "nik_pasien", [p["nik_pasien"] for p in pasien]):
        pj = penjamin.get(dp["id_penjamin"], {})
        guarantors.setdefault(dp["nik_pasien"], []).append({
            "nama_penjamin": pj.get("nama_penjamin"),
            "jenis_penjamin": pj.get("jenis_penjamin"),
            "status": dp.get("status"),
            "no_kartu": dp.get("no_kartu"),
        })

    data = []
    for p in pasien:
        phones = p.get("nomor_telepon") or []
        data.append({
            "nik_pasien": p["nik_pasien"],
            "nama_pasien": p["nama_pasien"],
            "tanggal_lahir_pasien": p.get("tanggal_lahir_pasien"),
            "telepon": phones[0]["no_telp_pasien"] if phones else None,
            "penjaminan": guarantors.get(p["nik_pasien"], []),
        })

    return {"data": data}


@router.get("/empat-layanan")
def pasien_empat_layanan(db=Depends(get_db)):
    surgery = [d["id_pelayanan_medis"] for d in db.operasi.find({}, {"_id": 0, "id_pelayanan_medis": 1})]
    services = list(chunked_find(db.pelayanan_medis, "id_pelayanan_medis", surgery,
                                 projection={"_id": 0, "no_registrasi": 1}))
    candidates = {s["no_registrasi"] for s in services}
    outpatient = {d["no_registrasi"] for d in chunked_find(db.pendaftaran, "no_registrasi", candidates,
                                                                   extra={"jenis_tindakan": "Rawat_Jalan"})}

    names = ("penanganan_medis", "operasi", "perawatan_klinis", "penunjang_medis")
    service_reg = {d["id_pelayanan_medis"]: d["no_registrasi"] for d in
                   chunked_find(db.pelayanan_medis, "no_registrasi", outpatient,
                                projection={"_id": 0, "id_pelayanan_medis": 1, "no_registrasi": 1})}
    per_name = {name: Counter(service_reg[d["id_pelayanan_medis"]] for d in
                              chunked_find(db[name], "id_pelayanan_medis", service_reg,
                                           projection={"_id": 0, "id_pelayanan_medis": 1}))
                for name in names}
    rows = [(r, {name: per_name[name][r] for name in names}) for r in outpatient
            if all(per_name[name][r] for name in names)]

    visits = {d["no_registrasi"]: d for d in chunked_find(db.pendaftaran, "no_registrasi", [r[0] for r in rows])}
    patients = {d["nik_pasien"]: d for d in
                chunked_find(db.pasien, "nik_pasien", {v["nik_pasien"] for v in visits.values()})}

    data = []
    for no_registrasi, counts in rows:
        visit = visits.get(no_registrasi)

        if visit is None:
            continue

        data.append({
            "nik_pasien": visit["nik_pasien"],
            "nama_pasien": patients.get(visit["nik_pasien"], {}).get("nama_pasien"),
            "no_registrasi": no_registrasi,
            "tanggal_daftar": visit["tanggal_daftar"],
            "penanganan": counts["penanganan_medis"],
            "operasi": counts["operasi"],
            "perawatan": counts["perawatan_klinis"],
            "penunjang": counts["penunjang_medis"],
        })

    data.sort(key=lambda r: (r["tanggal_daftar"], int(r["no_registrasi"])))
    return {"data": data}


@router.get("/{no_rm}/riwayat-medis")
def riwayat_medis(no_rm: str, db=Depends(get_db)):
    pasien = db.pasien.find_one({"no_rm": no_rm}, {"_id": 0})

    if pasien is None:
        raise HTTPException(status_code=404, detail="pasien tidak ditemukan")

    visits = list(db.pendaftaran.find({"nik_pasien": pasien["nik_pasien"]}, {"_id": 0}))
    visits.sort(key=lambda v: (v["tanggal_daftar"], int(v["no_registrasi"])))
    regs = [v["no_registrasi"] for v in visits]

    services = list(chunked_find(db.pelayanan_medis, "no_registrasi", regs))
    service_ids = [s["id_pelayanan_medis"] for s in services]
    diagnoses = list(chunked_find(db.diagnosis, "id_pelayanan_medis", service_ids))
    entry_visit = list(chunked_find(db.entri_pendaftaran, "no_registrasi", regs))
    entry_service = list(chunked_find(db.entri_pelayanan, "id_pelayanan_medis", service_ids))
    entry_ids = [e["id_entri"] for e in entry_visit + entry_service]
    entries = {e["id_entri"]: e for e in chunked_find(db.entri_rme, "id_entri", entry_ids)}

    service_reg = {s["id_pelayanan_medis"]: s["no_registrasi"] for s in services}
    per_visit = {r: {"services": 0, "diagnoses": set(), "entries": set()} for r in regs}

    for s in services:
        per_visit[s["no_registrasi"]]["services"] += 1

    for d in diagnoses:
        per_visit[service_reg[d["id_pelayanan_medis"]]]["diagnoses"].add(d["kode_diagnosis"])

    for e in entry_visit:
        per_visit[e["no_registrasi"]]["entries"].add(e["id_entri"])

    for e in entry_service:
        per_visit[service_reg[e["id_pelayanan_medis"]]]["entries"].add(e["id_entri"])

    data = []
    for v in visits:
        info = per_visit[v["no_registrasi"]]
        data.append({
            "no_registrasi": v["no_registrasi"],
            "tanggal_daftar": v["tanggal_daftar"],
            "jenis_tindakan": v["jenis_tindakan"],
            "hasil_penanganan": v.get("hasil_penanganan"),
            "jumlah_pelayanan": info["services"],
            "diagnosis": sorted(info["diagnoses"]),
            "jumlah_entri": len(info["entries"]),
            "catatan": sorted({entries[i]["isi_entri"] for i in info["entries"] if i in entries}),
        })

    return {"no_rm": no_rm, "nik_pasien": pasien["nik_pasien"], "data": data}


@router.post("", status_code=201)
def pasien_baru(body: PasienBaru, db=Depends(get_db)):
    require_pegawai(db, body.id_pegawai)

    if db.pasien.find_one({"nik_pasien": body.nik_pasien}) is not None:
        raise HTTPException(status_code=409, detail="NIK sudah terdaftar")

    umum = penjamin_umum(db)
    no_rm = next_id(db, "rme")
    writes = Writes(db)

    try:
        writes.insert("rme", {
            "no_rm": no_rm,
            "id_pegawai": body.id_pegawai,
            "alergi": [],
            "riwayat_penyakit": [],
            "obat_rutin": [],
            "imunisasi": [],
        })
        writes.insert("pasien", {
            "nik_pasien": body.nik_pasien,
            "no_rm": no_rm,
            "nama_pasien": body.nama_pasien,
            "tanggal_lahir_pasien": body.tanggal_lahir_pasien,
            "jenis_kelamin": body.jenis_kelamin,
            "jalan": body.jalan,
            "rt": body.rt,
            "rw": body.rw,
            "kota": body.kota,
            "provinsi": body.provinsi,
            "nomor_telepon": [{"no_telp_pasien": body.no_telp_pasien}],
        })
        writes.insert("daftar_penjaminan", {
            "nik_pasien": body.nik_pasien,
            "id_penjamin": umum["id_penjamin"],
            "no_kartu": None,
            "status": "Aktif",
        })

    except Exception:
        writes.rollback()
        raise HTTPException(status_code=503, detail="gagal menyimpan pasien baru")

    return {"nik_pasien": body.nik_pasien, "no_rm": no_rm, "id_penjamin": umum["id_penjamin"]}
