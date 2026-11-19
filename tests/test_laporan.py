from datetime import date

from app import cache
from app.routers.laporan import months_ago


def test_months_ago_handles_year_and_short_months():
    assert months_ago(date(2026, 11, 19), 3) == date(2026, 8, 19)
    assert months_ago(date(2026, 1, 15), 3) == date(2025, 10, 15)
    assert months_ago(date(2026, 3, 31), 1) == date(2026, 2, 28)


def test_s02_quota_per_schedule(client):
    r = client.get("/api/jadwal-dokter/kuota", params={"tanggal": "2026-10-05"})
    assert r.status_code == 200
    first, second = r.json()["data"]
    assert first == {"id_jadwal": "1", "hari": "Senin", "nama_dokter": "dr. Budi", "spesialisasi": "Penyakit Dalam",
                     "ruang_unit": "Poli Umum", "kuota": 2, "jumlah_pasien": 2, "sisa_kuota": 0}
    assert (second["jumlah_pasien"], second["sisa_kuota"], second["spesialisasi"]) == (0, 1, "Anak")


def test_s02_ignores_non_outpatient_visits_and_other_days(client):
    rows = client.get("/api/jadwal-dokter/kuota", params={"tanggal": "2026-10-06"}).json()["data"]
    assert [r["jumlah_pasien"] for r in rows] == [0, 0]
    assert [r["jumlah_pasien"] for r in client.get("/api/jadwal-dokter/kuota", params={"tanggal": "2030-01-01"}).json()["data"]] == [0, 0]


def test_s02_defaults_to_today_and_rejects_bad_date(client):
    assert client.get("/api/jadwal-dokter/kuota").json()["tanggal"] == date.today().isoformat()
    assert client.get("/api/jadwal-dokter/kuota", params={"tanggal": "x"}).status_code == 422


def test_s03_only_inpatient_rooms_with_space(client):
    assert client.get("/api/ruangan/tersedia").json()["data"] == [{
        "ruang_unit": "Rawat Inap A", "nama_ruangan": "Kamar 001", "nama_kelas": "VIP",
        "kapasitas_ruangan": 2, "tempat_terisi": 1, "sisa_tempat": 1}]


def test_s03_room_becomes_available_when_patient_leaves(client, db):
    db.penempatan_ruangan.update_one({"id_ruangan": "2"}, {"$set": {"waktu_keluar": "2026-10-07 08:00:00"}})
    assert [r["nama_ruangan"] for r in client.get("/api/ruangan/tersedia").json()["data"]] == ["Kamar 001", "Kamar 002"]


def test_s06_daily_counts_and_cache(client, redis):
    params = {"dari": "2026-10-08", "sampai": "2026-10-09"}
    first = client.get("/api/penunjang/rekap-harian", params=params).json()
    assert first["source"] == "mongodb"
    assert first["data"] == [
        {"tanggal_permintaan": "2026-10-08", "laboratorium": 1, "radiologi": 1, "farmasi": 0, "gizi": 0, "total": 2},
        {"tanggal_permintaan": "2026-10-09", "laboratorium": 0, "radiologi": 0, "farmasi": 1, "gizi": 0, "total": 1}]
    second = client.get("/api/penunjang/rekap-harian", params=params).json()
    assert second["source"] == "redis" and second["data"] == first["data"]


def test_s06_range_bounds_and_errors(client):
    one = client.get("/api/penunjang/rekap-harian", params={"dari": "2026-10-09", "sampai": "2026-10-09"}).json()
    assert [d["tanggal_permintaan"] for d in one["data"]] == ["2026-10-09"]
    assert client.get("/api/penunjang/rekap-harian", params={"dari": "2030-01-01", "sampai": "2030-01-02"}).json()["data"] == []
    assert client.get("/api/penunjang/rekap-harian", params={"dari": "2026-10-10", "sampai": "2026-10-01"}).status_code == 422
    assert client.get("/api/penunjang/rekap-harian", params={"dari": "2026-10-10"}).status_code == 422


def test_s06_new_request_makes_cached_report_stale(client):
    params = {"dari": "2026-10-08", "sampai": "2026-10-09"}
    client.get("/api/penunjang/rekap-harian", params=params)
    assert client.get("/api/penunjang/rekap-harian", params=params).json()["source"] == "redis"
    client.post("/api/pendaftaran/1/penunjang", json={
        "jenis": "laboratorium", "id_layanan": "306", "id_unit": "32", "id_pegawai_medis": "125", "id_pegawai_paramedis": "360"})
    assert client.get("/api/penunjang/rekap-harian", params=params).json()["source"] == "mongodb"


def test_s07_monthly_revenue(client):
    out = client.get("/api/laporan/pendapatan-bulanan", params={"tahun": 2026, "bulan": 10}).json()
    assert out["source"] == "mongodb"
    assert out["data"] == [{"jenis_tindakan": "Rawat_Jalan", "jumlah_kunjungan": 2, "total_pendapatan": 1350000.0,
                            "rata_rata_per_kunjungan": 675000, "tunai": 100000.0, "non_tunai": 1250000.0}]


def test_s07_december_and_empty_month_and_validation(client):
    assert client.get("/api/laporan/pendapatan-bulanan", params={"tahun": 2026, "bulan": 12}).json()["data"] == []
    assert client.get("/api/laporan/pendapatan-bulanan", params={"tahun": 2026, "bulan": 13}).status_code == 422
    assert client.get("/api/laporan/pendapatan-bulanan", params={"tahun": 2026}).status_code == 422


def test_s07_payment_changes_refresh_the_cache(client):
    params = {"tahun": 2026, "bulan": 10}
    client.get("/api/laporan/pendapatan-bulanan", params=params)
    assert client.get("/api/laporan/pendapatan-bulanan", params=params).json()["source"] == "redis"
    client.patch("/api/pembayaran/3/status", json={"status": "Berhasil"})
    out = client.get("/api/laporan/pendapatan-bulanan", params=params).json()
    assert out["source"] == "mongodb"
    assert [(d["jenis_tindakan"], d["jumlah_kunjungan"], d["total_pendapatan"]) for d in out["data"]] == [
        ("Rawat_Jalan", 2, 1350000.0), ("IGD", 1, 150000.0)]


def test_s08_claims_per_guarantor_and_refresh_after_new_claim(client, db):
    out = client.get("/api/laporan/klaim-penjamin").json()
    assert out["data"] == [{"nama_penjamin": "BPJS Kesehatan", "jenis_penjamin": "JKN",
                            "jumlah_klaim": 1, "total_nilai_klaim": 1300000.0}]
    assert client.get("/api/laporan/klaim-penjamin").json()["source"] == "redis"
    db.daftar_penjaminan.insert_one({"nik_pasien": "3171000000000002", "id_penjamin": "2", "no_kartu": "9", "status": "Aktif"})
    assert client.post("/api/pendaftaran/3/klaim").status_code == 201
    fresh = client.get("/api/laporan/klaim-penjamin").json()
    assert fresh["source"] == "mongodb"
    assert [(d["nama_penjamin"], d["total_nilai_klaim"]) for d in fresh["data"]] == [
        ("BPJS Kesehatan", 1300000.0), ("Asuransi Sehat", 250000.0)]


def test_s08_visit_without_priced_service_is_left_out(client, db):
    db.pelayanan_medis.delete_many({"no_registrasi": "1"})
    assert client.get("/api/laporan/klaim-penjamin").json()["data"] == []


def test_s09_top_three_services_per_unit(client):
    out = client.get("/api/laporan/layanan-terpopuler", params={"tanggal_acuan": "2026-11-19"}).json()
    assert out["source"] == "mongodb"
    assert out["data"] == [
        {"ruang_unit": "Poli Umum", "nama_layanan": "Konsultasi", "jumlah_penggunaan": 3, "peringkat": 1},
        {"ruang_unit": "Poli Umum", "nama_layanan": "Operasi Kecil", "jumlah_penggunaan": 1, "peringkat": 2},
        {"ruang_unit": "Poli Umum", "nama_layanan": "Perawatan Luka", "jumlah_penggunaan": 1, "peringkat": 3},
        {"ruang_unit": "Laboratorium", "nama_layanan": "Hematologi", "jumlah_penggunaan": 3, "peringkat": 1}]


def test_s09_only_top_three_and_time_window(client, db):
    db.layanan.insert_one({"id_layanan": "90", "nama_layanan": "Lain", "kategori": "Tindakan", "tarif": []})
    db.pelayanan_medis.insert_one({"id_pelayanan_medis": "20", "no_registrasi": "1", "id_layanan": "90", "versi_harga": "2026",
                                   "id_unit": "11", "waktu_mulai": "2026-10-07 08:00:00.000000", "waktu_selesai": None})
    poli = [d for d in client.get("/api/laporan/layanan-terpopuler", params={"tanggal_acuan": "2026-11-19"}).json()["data"]
            if d["ruang_unit"] == "Poli Umum"]
    assert len(poli) == 3
    assert client.get("/api/laporan/layanan-terpopuler",
                      params={"tanggal_acuan": "2026-12-19", "bulan_terakhir": 1}).json()["data"] == []
    assert client.get("/api/laporan/layanan-terpopuler", params={"bulan_terakhir": 0}).status_code == 422


def test_reports_work_without_redis(client, monkeypatch):
    monkeypatch.setattr(cache, "redis", None)
    for _ in range(2):
        out = client.get("/api/laporan/pendapatan-bulanan", params={"tahun": 2026, "bulan": 10}).json()
        assert out["source"] == "mongodb" and out["data"][0]["jumlah_kunjungan"] == 2
