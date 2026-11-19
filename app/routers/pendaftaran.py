from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.cache import bump_report
from app.common import (DAYS, Detail, Id, Nik, Text, Time, Writes, Year, get_master, get_pendaftaran, money, next_id,
                        now_ts, parse_date, penjamin_umum, require_pegawai, today, visit_counts)
from app.database import get_db

router = APIRouter(prefix="/api/pendaftaran", tags=["pendaftaran"])

SUPPORT_LABELS = {"laboratorium": "Laboratorium", "radiologi": "Radiologi", "farmasi": "Farmasi", "gizi": "Gizi"}

SUPPORT_FIELDS = {
    "laboratorium": (["nama_laboratorium", "jenis_pemeriksaan"], ["hasil_laboratorium"]),
    "radiologi": (["nama_ruang_radiologi", "jenis_pemeriksaan_radiologi"], ["hasil_radiologi"]),
    "farmasi": ([], ["laporan_transaksi_obat"]),
    "gizi": (["nama_dapur", "jenis_diet", "kapasitas_porsi", "id_pegawai_koki"], []),
}


class RawatJalan(BaseModel):
    nik_pasien: Nik
    id_jadwal: Id
    tanggal: Text
    id_penjamin: Id
    id_pegawai: Id
    jam_daftar: Time | None = None


class Igd(BaseModel):
    nik_pasien: Nik
    id_pegawai: Id
    id_penjamin: Id | None = None


class PenjaminBaru(BaseModel):
    id_penjamin: Id
    no_kartu: Annotated[str, Field(pattern=r"^[0-9A-Za-z]{1,30}$")]


class Admisi(BaseModel):
    jenis_upgrade: Literal["0", "1"]
    catatan_admisi: Text
    id_pegawai: Id
    id_ruangan: Id


class Penunjang(BaseModel):
    jenis: Literal["laboratorium", "radiologi", "farmasi", "gizi"]
    id_layanan: Id
    id_unit: Id
    id_pegawai_medis: Id
    id_pegawai_paramedis: Id
    versi_harga: Year = "2026"
    detail: Detail = {}


class Pembayaran(BaseModel):
    metode_pembayaran: Literal["Tunai", "Non-Tunai"]
    id_pegawai: Id


def new_visit(no_registrasi, tanggal, jam, jenis, nik, id_penjamin, id_pegawai):
    return {
        "no_registrasi": no_registrasi,
        "tanggal_daftar": tanggal,
        "jam_daftar": jam,
        "jenis_tindakan": jenis,
        "hasil_penanganan": None,
        "nik_pasien": nik,
        "id_penjamin": id_penjamin,
        "id_pegawai": id_pegawai,
        "klaim_asuransi": [],
    }


def require(db, collection, field, value, label):
    doc = db[collection].find_one({field: value}, {"_id": 0})

    if doc is None:
        raise HTTPException(status_code=404, detail=f"{label} tidak ditemukan")

    return doc


@router.get("/{no_registrasi}/layanan")
def layanan_kunjungan(no_registrasi: str, db=Depends(get_db)):
    get_pendaftaran(db, no_registrasi)

    services = {s["id_pelayanan_medis"]: s for s in
                db.pelayanan_medis.find({"no_registrasi": no_registrasi}, {"_id": 0})}
    support = db.penunjang_medis.find({"id_pelayanan_medis": {"$in": list(services)}}, {"_id": 0})
    layanan = get_master(db, "layanan", "id_layanan")
    unit = get_master(db, "unit_layanan", "id_unit")
    pegawai = get_master(db, "pegawai", "id_pegawai")

    rows = []
    for doc in support:
        service = services[doc["id_pelayanan_medis"]]

        for key, label in SUPPORT_LABELS.items():
            detail = doc.get(key)

            if detail:
                rows.append({
                    "jenis_layanan": label,
                    "no_registrasi": no_registrasi,
                    "nama_layanan": layanan.get(service["id_layanan"], {}).get("nama_layanan"),
                    "ruang_unit": unit.get(service["id_unit"], {}).get("ruang_unit"),
                    "nama_petugas": pegawai.get(detail.get("id_pegawai"), {}).get("nama"),
                })

    rows.sort(key=lambda r: (r["jenis_layanan"], r["nama_layanan"] or ""))
    return {"data": rows}


@router.post("/rawat-jalan", status_code=201)
def daftar_rawat_jalan(body: RawatJalan, db=Depends(get_db)):
    tanggal = parse_date(body.tanggal)
    require_pegawai(db, body.id_pegawai)
    require(db, "pasien", "nik_pasien", body.nik_pasien, "pasien")
    require(db, "penjamin", "id_penjamin", body.id_penjamin, "penjamin")
    jadwal = require(db, "jadwal_dokter", "id_jadwal", body.id_jadwal, "jadwal")

    day = DAYS[date.fromisoformat(tanggal).isoweekday() - 1]
    if jadwal["hari"] != day:
        raise HTTPException(status_code=409, detail=f"jadwal ini hari {jadwal['hari']}, bukan {day}")

    if visit_counts(db, tanggal, body.id_jadwal).get(body.id_jadwal, 0) >= int(jadwal["kuota"]):
        raise HTTPException(status_code=409, detail="kuota jadwal sudah penuh")

    no_registrasi = next_id(db, "pendaftaran")
    jam = body.jam_daftar or datetime.now().strftime("%H:%M:%S")
    writes = Writes(db)

    try:
        writes.insert("pendaftaran", new_visit(no_registrasi, tanggal, jam, "Rawat_Jalan", body.nik_pasien,
                                               body.id_penjamin, body.id_pegawai))
        writes.insert("rawat_jalan", {"no_registrasi": no_registrasi})

    except Exception:
        writes.rollback()
        raise HTTPException(status_code=503, detail="gagal menyimpan pendaftaran")

    return {"no_registrasi": no_registrasi, "tanggal_daftar": tanggal}


@router.post("/igd", status_code=201)
def daftar_igd(body: Igd, db=Depends(get_db)):
    require_pegawai(db, body.id_pegawai)
    require(db, "pasien", "nik_pasien", body.nik_pasien, "pasien")
    id_penjamin = body.id_penjamin or penjamin_umum(db)["id_penjamin"]
    no_registrasi = next_id(db, "pendaftaran")
    writes = Writes(db)

    try:
        writes.insert("pendaftaran", new_visit(no_registrasi, today(), datetime.now().strftime("%H:%M:%S"), "IGD",
                                               body.nik_pasien, id_penjamin, body.id_pegawai))
        writes.insert("igd", {"no_registrasi": no_registrasi})

    except Exception:
        writes.rollback()
        raise HTTPException(status_code=503, detail="gagal menyimpan pendaftaran IGD")

    return {"no_registrasi": no_registrasi, "id_penjamin": id_penjamin}


@router.patch("/{no_registrasi}/penjamin")
def perbarui_penjamin_igd(no_registrasi: str, body: PenjaminBaru, db=Depends(get_db)):
    visit = get_pendaftaran(db, no_registrasi)

    if db.igd.find_one({"no_registrasi": no_registrasi}) is None:
        raise HTTPException(status_code=409, detail="bukan kunjungan IGD")

    require(db, "penjamin", "id_penjamin", body.id_penjamin, "penjamin")

    if db.daftar_penjaminan.find_one({"nik_pasien": visit["nik_pasien"], "id_penjamin": body.id_penjamin}):
        raise HTTPException(status_code=409, detail="pasien sudah punya penjaminan ini")

    writes = Writes(db)

    try:
        writes.insert("daftar_penjaminan", {
            "nik_pasien": visit["nik_pasien"],
            "id_penjamin": body.id_penjamin,
            "no_kartu": body.no_kartu,
            "status": "Aktif",
        })
        db.pendaftaran.update_one({"no_registrasi": no_registrasi}, {"$set": {"id_penjamin": body.id_penjamin}})

    except Exception:
        writes.rollback()
        raise HTTPException(status_code=503, detail="gagal memperbarui penjamin")

    return {"no_registrasi": no_registrasi, "id_penjamin": body.id_penjamin}


@router.post("/{no_registrasi}/admisi", status_code=201)
def admisi_rawat_inap(no_registrasi: str, body: Admisi, db=Depends(get_db)):
    get_pendaftaran(db, no_registrasi)
    require_pegawai(db, body.id_pegawai)
    ruangan = require(db, "ruangan", "id_ruangan", body.id_ruangan, "ruangan")

    if db.admisi.find_one({"no_registrasi": no_registrasi}) is not None:
        raise HTTPException(status_code=409, detail="pendaftaran ini sudah diadmisi")

    if ruangan["status_ruangan"] != "Tersedia":
        raise HTTPException(status_code=409, detail="ruangan tidak tersedia")

    if not ruangan.get("rawat_inap"):
        raise HTTPException(status_code=409, detail="bukan ruangan rawat inap")

    occupied = db.penempatan_ruangan.count_documents({"id_ruangan": body.id_ruangan, "waktu_keluar": None})
    if occupied >= int(ruangan["kapasitas_ruangan"]):
        raise HTTPException(status_code=409, detail="ruangan sudah penuh")

    writes = Writes(db)

    try:
        writes.insert("admisi", {
            "no_registrasi": no_registrasi,
            "jenis_upgrade": body.jenis_upgrade,
            "catatan_admisi": body.catatan_admisi,
            "id_pegawai": body.id_pegawai,
        })
        writes.insert("penempatan_ruangan", {
            "no_registrasi": no_registrasi,
            "waktu_masuk": now_ts(),
            "id_ruangan": body.id_ruangan,
            "waktu_keluar": None,
        })

    except Exception:
        writes.rollback()
        raise HTTPException(status_code=503, detail="gagal menyimpan admisi")

    return {"no_registrasi": no_registrasi, "id_ruangan": body.id_ruangan}


@router.post("/{no_registrasi}/penunjang", status_code=201)
def permintaan_penunjang(no_registrasi: str, body: Penunjang, db=Depends(get_db)):
    get_pendaftaran(db, no_registrasi)
    require_pegawai(db, body.id_pegawai_medis, body.id_pegawai_paramedis)
    layanan = require(db, "layanan", "id_layanan", body.id_layanan, "layanan")
    require(db, "unit_layanan", "id_unit", body.id_unit, "unit")

    if not any(t["versi_harga"] == body.versi_harga for t in layanan.get("tarif", [])):
        raise HTTPException(status_code=409, detail="tarif versi ini tidak ada untuk layanan")

    id_pelayanan = next_id(db, "pelayanan_medis")
    request_fields, result_fields = SUPPORT_FIELDS[body.jenis]
    detail = {f: body.detail.get(f) for f in request_fields} | dict.fromkeys(result_fields)
    detail["id_pegawai"] = body.id_pegawai_paramedis
    support = {"laboratorium": None, "radiologi": None, "farmasi": None, "gizi": None, body.jenis: detail}
    writes = Writes(db)

    try:
        writes.insert("pelayanan_medis", {
            "id_pelayanan_medis": id_pelayanan,
            "waktu_mulai": now_ts(),
            "waktu_selesai": None,
            "no_registrasi": no_registrasi,
            "id_layanan": body.id_layanan,
            "versi_harga": body.versi_harga,
            "id_unit": body.id_unit,
        })
        writes.insert("penunjang_medis", {
            "id_pelayanan_medis": id_pelayanan,
            "laporan_penunjang_medis": None,
            "tanggal_permintaan": today(),
            "status_kebutuhan": "Diproses",
            "id_pegawai_medis": body.id_pegawai_medis,
            "id_pegawai_paramedis": body.id_pegawai_paramedis,
            **support,
        })
        writes.insert(body.jenis, {"id_pelayanan_medis": id_pelayanan, **detail})

    except Exception:
        writes.rollback()
        raise HTTPException(status_code=503, detail="gagal menyimpan permintaan penunjang")

    bump_report("penunjang", "layanan-terpopuler", "klaim")
    return {"id_pelayanan_medis": id_pelayanan, "jenis": body.jenis, "status_kebutuhan": "Diproses"}


@router.post("/{no_registrasi}/pembayaran", status_code=201)
def catat_pembayaran(no_registrasi: str, body: Pembayaran, db=Depends(get_db)):
    get_pendaftaran(db, no_registrasi)
    require_pegawai(db, body.id_pegawai)
    layanan = get_master(db, "layanan", "id_layanan")

    total = money(0)
    for s in db.pelayanan_medis.find({"no_registrasi": no_registrasi, "waktu_selesai": {"$ne": None}}, {"_id": 0}):
        for tarif in layanan.get(s["id_layanan"], {}).get("tarif", []):
            if tarif["versi_harga"] == s["versi_harga"]:
                total += money(tarif["harga"])

    if total == 0:
        raise HTTPException(status_code=409, detail="belum ada pelayanan selesai dengan tarif")

    if db.pembayaran.find_one({"no_registrasi": no_registrasi, "status_pembayaran": "Berhasil"}) is not None:
        raise HTTPException(status_code=409, detail="pendaftaran ini sudah dibayar")

    no_billing = next_id(db, "pembayaran")
    now = datetime.now()
    db.pembayaran.insert_one({
        "no_billing": no_billing,
        "tanggal_pembayaran": now.strftime("%Y-%m-%d"),
        "waktu_pembayaran": now.strftime("%H:%M:%S.%f"),
        "metode_pembayaran": body.metode_pembayaran,
        "status_pembayaran": "Gagal",
        "id_pegawai": body.id_pegawai,
        "no_registrasi": no_registrasi,
        "jumlah_pembayaran": f"{total:.2f}",
    })

    bump_report("pendapatan")
    return {"no_billing": no_billing, "jumlah_pembayaran": f"{total:.2f}", "status_pembayaran": "Gagal"}


@router.post("/{no_registrasi}/klaim", status_code=201)
def ajukan_klaim(no_registrasi: str, db=Depends(get_db)):
    visit = get_pendaftaran(db, no_registrasi)
    penjamin = require(db, "penjamin", "id_penjamin", visit["id_penjamin"], "penjamin")

    if penjamin["jenis_penjamin"] == "Pribadi":
        raise HTTPException(status_code=409, detail="penjamin pribadi tidak bisa mengajukan klaim")

    if db.daftar_penjaminan.find_one({"nik_pasien": visit["nik_pasien"], "id_penjamin": visit["id_penjamin"]}) is None:
        raise HTTPException(status_code=409, detail="pasien tidak terdaftar pada penjamin ini")

    if visit.get("klaim_asuransi"):
        raise HTTPException(status_code=409, detail="klaim untuk pendaftaran ini sudah ada")

    id_asuransi = next_id(db, "klaim_asuransi")
    result = db.pendaftaran.update_one({"no_registrasi": no_registrasi, "klaim_asuransi": []}, {"$push": {"klaim_asuransi": {
        "id_asuransi": id_asuransi,
        "laporan_rumah_sakit": f"Resume medis kunjungan {no_registrasi}",
        "rincian_klaim_asuransi": "Klaim INA-CBG, status Diajukan",
    }}})

    if result.matched_count == 0:
        raise HTTPException(status_code=409, detail="klaim untuk pendaftaran ini sudah ada")

    bump_report("klaim")
    return {"no_registrasi": no_registrasi, "id_asuransi": id_asuransi}
