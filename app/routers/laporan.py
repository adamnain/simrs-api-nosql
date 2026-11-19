import calendar
from collections import Counter
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, Query

from app.cache import cached_report
from app.common import chunked_find, get_master, money, parse_date, today, visit_counts
from app.database import get_db

router = APIRouter(tags=["laporan"])

SUPPORT_TYPES = ("laboratorium", "radiologi", "farmasi", "gizi")


def months_ago(d: date, months: int) -> date:
    year, month = divmod(d.year * 12 + d.month - 1 - months, 12)
    month += 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


@router.get("/api/jadwal-dokter/kuota")
def kuota_jadwal(tanggal: str | None = None, db=Depends(get_db)):
    tanggal = parse_date(tanggal) if tanggal else today()
    counts = visit_counts(db, tanggal)
    pegawai = get_master(db, "pegawai", "id_pegawai")
    unit = get_master(db, "unit_layanan", "id_unit")

    rows = []
    for j in sorted(db.jadwal_dokter.find({}, {"_id": 0}), key=lambda j: int(j["id_jadwal"])):
        doctor = pegawai.get(j["id_pegawai"], {})
        used = counts.get(j["id_jadwal"], 0)
        rows.append({
            "id_jadwal": j["id_jadwal"],
            "hari": j["hari"],
            "nama_dokter": doctor.get("nama"),
            "spesialisasi": ((doctor.get("tenaga_medis") or {}).get("dokter") or {}).get("spesialisasi"),
            "ruang_unit": unit.get(j["id_unit"], {}).get("ruang_unit"),
            "kuota": int(j["kuota"]),
            "jumlah_pasien": used,
            "sisa_kuota": int(j["kuota"]) - used,
        })

    return {"tanggal": tanggal, "data": rows}


@router.get("/api/ruangan/tersedia")
def ruangan_tersedia(db=Depends(get_db)):
    rooms = [r for r in db.ruangan.find({"status_ruangan": "Tersedia"}, {"_id": 0}) if r.get("rawat_inap")]
    occupied = Counter(
        p["id_ruangan"] for p in chunked_find(db.penempatan_ruangan, "id_ruangan", [r["id_ruangan"] for r in rooms],
                                              extra={"waktu_keluar": None})
    )
    kelas = get_master(db, "kelas_ruangan", "id_kelas")
    unit = get_master(db, "unit_layanan", "id_unit")

    rows = []
    for r in sorted(rooms, key=lambda r: int(r["id_ruangan"])):
        capacity = int(r["kapasitas_ruangan"])
        used = occupied.get(r["id_ruangan"], 0)

        if used < capacity:
            rows.append({
                "ruang_unit": unit.get(r["id_unit"], {}).get("ruang_unit"),
                "nama_ruangan": r["nama_ruangan"],
                "nama_kelas": kelas.get(r["rawat_inap"]["id_kelas"], {}).get("nama_kelas"),
                "kapasitas_ruangan": capacity,
                "tempat_terisi": used,
                "sisa_tempat": capacity - used,
            })

    return {"data": rows}


@router.get("/api/penunjang/rekap-harian")
def rekap_penunjang(dari: str, sampai: str, db=Depends(get_db)):
    dari, sampai = parse_date(dari), parse_date(sampai)

    if dari > sampai:
        raise HTTPException(status_code=422, detail="dari harus sebelum atau sama dengan sampai")

    if (date.fromisoformat(sampai) - date.fromisoformat(dari)).days > 366:
        raise HTTPException(status_code=422, detail="rentang tanggal maksimal 366 hari")

    def compute():
        per_day = {}
        docs = db.penunjang_medis.find({"tanggal_permintaan": {"$gte": dari, "$lte": sampai}}, {"_id": 0})

        for d in docs:
            row = per_day.setdefault(d["tanggal_permintaan"], dict.fromkeys(SUPPORT_TYPES, 0) | {"total": 0})
            row["total"] += 1

            for t in SUPPORT_TYPES:
                if d.get(t):
                    row[t] += 1

        return [{"tanggal_permintaan": day, **row} for day, row in sorted(per_day.items())]

    return cached_report("penunjang", f"{dari}:{sampai}", compute, ttl=300)


@router.get("/api/laporan/pendapatan-bulanan")
def pendapatan_bulanan(tahun: int = Query(ge=2000, le=2100), bulan: int = Query(ge=1, le=12), db=Depends(get_db)):
    start = f"{tahun:04d}-{bulan:02d}-01"
    end = f"{tahun + (bulan == 12):04d}-{bulan % 12 + 1:02d}-01"

    def compute():
        payments = list(db.pembayaran.find(
            {"status_pembayaran": "Berhasil", "tanggal_pembayaran": {"$gte": start, "$lt": end}}, {"_id": 0}))
        kind = {v["no_registrasi"]: v["jenis_tindakan"] for v in chunked_find(
            db.pendaftaran, "no_registrasi", {p["no_registrasi"] for p in payments})}

        groups = {}
        for p in payments:
            g = groups.setdefault(kind[p["no_registrasi"]], {
                "visits": set(), "total": money(0), "tunai": money(0), "non_tunai": money(0)})
            amount = money(p["jumlah_pembayaran"])
            g["visits"].add(p["no_registrasi"])
            g["total"] += amount
            g["tunai" if p["metode_pembayaran"] == "Tunai" else "non_tunai"] += amount

        rows = [{
            "jenis_tindakan": name,
            "jumlah_kunjungan": len(g["visits"]),
            "total_pendapatan": float(g["total"]),
            "rata_rata_per_kunjungan": int((g["total"] / len(g["visits"])).quantize(Decimal(1), rounding=ROUND_HALF_UP)),
            "tunai": float(g["tunai"]),
            "non_tunai": float(g["non_tunai"]),
        } for name, g in groups.items()]

        return sorted(rows, key=lambda r: -r["total_pendapatan"])

    return cached_report("pendapatan", f"{tahun}-{bulan}", compute)


@router.get("/api/laporan/klaim-penjamin")
def klaim_penjamin(db=Depends(get_db)):
    def compute():
        visits = list(db.pendaftaran.find({"klaim_asuransi": {"$ne": []}}, {"_id": 0}))
        layanan = get_master(db, "layanan", "id_layanan")
        penjamin = get_master(db, "penjamin", "id_penjamin")

        bill = {}
        for s in chunked_find(db.pelayanan_medis, "no_registrasi", [v["no_registrasi"] for v in visits]):
            for t in layanan.get(s["id_layanan"], {}).get("tarif", []):
                if t["versi_harga"] == s["versi_harga"]:
                    bill[s["no_registrasi"]] = bill.get(s["no_registrasi"], money(0)) + money(t["harga"])

        groups = {}
        for v in visits:
            if v["no_registrasi"] not in bill:
                continue

            claims = len(v["klaim_asuransi"])
            g = groups.setdefault(v["id_penjamin"], {"jumlah_klaim": 0, "total": money(0)})
            g["jumlah_klaim"] += claims
            g["total"] += bill[v["no_registrasi"]] * claims

        rows = [{
            "nama_penjamin": penjamin.get(pid, {}).get("nama_penjamin"),
            "jenis_penjamin": penjamin.get(pid, {}).get("jenis_penjamin"),
            "jumlah_klaim": g["jumlah_klaim"],
            "total_nilai_klaim": float(g["total"]),
        } for pid, g in groups.items()]

        return sorted(rows, key=lambda r: -r["total_nilai_klaim"])

    return cached_report("klaim", "all", compute)


@router.get("/api/laporan/layanan-terpopuler")
def layanan_terpopuler(bulan_terakhir: int = Query(3, ge=1, le=24), tanggal_acuan: str | None = None,
                       db=Depends(get_db)):
    acuan = parse_date(tanggal_acuan) if tanggal_acuan else today()
    cutoff = months_ago(date.fromisoformat(acuan), bulan_terakhir).isoformat()

    def compute():
        counted = db.pelayanan_medis.aggregate([
            {"$match": {"waktu_mulai": {"$gte": cutoff}}},
            {"$group": {"_id": {"unit": "$id_unit", "layanan": "$id_layanan"}, "jumlah": {"$sum": 1}}},
        ])
        layanan = get_master(db, "layanan", "id_layanan")
        unit = get_master(db, "unit_layanan", "id_unit")

        per_unit = {}
        for c in counted:
            per_unit.setdefault(c["_id"]["unit"], []).append((c["_id"]["layanan"], c["jumlah"]))

        rows = []
        for id_unit, items in sorted(per_unit.items(), key=lambda kv: int(kv[0])):
            items.sort(key=lambda it: (-it[1], int(it[0])))

            for rank, (id_layanan, jumlah) in enumerate(items[:3], start=1):
                rows.append({
                    "ruang_unit": unit.get(id_unit, {}).get("ruang_unit"),
                    "nama_layanan": layanan.get(id_layanan, {}).get("nama_layanan"),
                    "jumlah_penggunaan": jumlah,
                    "peringkat": rank,
                })

        return rows

    return cached_report("layanan-terpopuler", f"{bulan_terakhir}:{acuan}", compute)
