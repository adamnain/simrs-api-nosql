from datetime import datetime


def test_w06_records_requested_treatment_and_finishes_it(client, db):
    body = {"no_registrasi": "1", "id_pegawai": "130", "id_pegawai_peminta": "125"}
    r = client.post("/api/pelayanan/penanganan-rujukan", json=body)
    assert r.status_code == 201
    assert r.json()["id_pelayanan_medis"] == "9" and r.json()["id_layanan"] == "63"
    service = db.pelayanan_medis.find_one({"id_pelayanan_medis": "9"})
    assert service["id_unit"] == "11" and service["versi_harga"] == "2026" and service["no_registrasi"] == "1"
    start = datetime.strptime(service["waktu_mulai"], "%Y-%m-%d %H:%M:%S.%f")
    end = datetime.strptime(service["waktu_selesai"], "%Y-%m-%d %H:%M:%S.%f")
    assert 29 * 60 <= (end - start).total_seconds() <= 31 * 60
    handling = db.penanganan_medis.find_one({"id_pelayanan_medis": "9"})
    assert (handling["id_pegawai"], handling["id_pegawai_peminta"], handling["id_jadwal"]) == ("130", "125", None)


def test_w06_picks_lowest_unit_then_service(client, db):
    db.layanan.insert_one({"id_layanan": "5", "nama_layanan": "Cek", "kategori": "Pemeriksaan",
                           "tarif": [{"versi_harga": "2026", "harga": "1.00"}]})
    db.penyediaan_layanan.insert_one({"id_unit": "11", "id_layanan": "5"})
    r = client.post("/api/pelayanan/penanganan-rujukan",
                    json={"no_registrasi": "1", "id_pegawai": "130", "id_pegawai_peminta": "125"})
    assert r.json()["id_layanan"] == "5"


def test_w06_refusals(client, db):
    body = {"no_registrasi": "1", "id_pegawai": "130", "id_pegawai_peminta": "125"}
    assert client.post("/api/pelayanan/penanganan-rujukan", json={**body, "no_registrasi": "99"}).status_code == 404
    assert client.post("/api/pelayanan/penanganan-rujukan", json={**body, "versi_harga": "1999"}).status_code == 409
    assert client.post("/api/pelayanan/penanganan-rujukan", json={"no_registrasi": "1"}).status_code == 422
    assert db.pelayanan_medis.count_documents({}) == 8


def test_w09_marks_payment_successful(client, db):
    r = client.patch("/api/pembayaran/3/status", json={"status": "Berhasil"})
    assert r.status_code == 200 and r.json() == {"no_billing": "3", "status_pembayaran": "Berhasil"}
    assert db.pembayaran.find_one({"no_billing": "3"})["status_pembayaran"] == "Berhasil"


def test_w09_refuses_second_successful_payment_for_same_visit(client, db):
    db.pembayaran.insert_one({"no_billing": "5", "no_registrasi": "2", "status_pembayaran": "Berhasil"})
    assert client.patch("/api/pembayaran/3/status", json={"status": "Berhasil"}).status_code == 409
    assert db.pembayaran.find_one({"no_billing": "3"})["status_pembayaran"] == "Gagal"


def test_unknown_staff_id_is_refused_and_nothing_is_written(client, db):
    before = db.pelayanan_medis.count_documents({})
    r = client.post("/api/pelayanan/penanganan-rujukan",
                    json={"no_registrasi": "1", "id_pegawai": "99999999", "id_pegawai_peminta": "125"})
    assert r.status_code == 404 and db.pelayanan_medis.count_documents({}) == before
    assert client.post("/api/pendaftaran/igd", json={"nik_pasien": "3171000000000001", "id_pegawai": "99999999"}
                       ).status_code == 404
    assert client.patch("/api/pembayaran/3/status", json={"status": "Berhasil"}).status_code == 200


def test_w06_makes_cached_reports_fresh(client):
    for path in ("/api/laporan/klaim-penjamin",):
        client.get(path)
        assert client.get(path).json()["source"] == "redis"
        client.post("/api/pelayanan/penanganan-rujukan",
                    json={"no_registrasi": "1", "id_pegawai": "130", "id_pegawai_peminta": "125"})
        assert client.get(path).json()["source"] == "mongodb"


def test_w10_claim_lost_to_a_parallel_request_is_409(client, db, monkeypatch):
    from app.routers import pendaftaran
    real = pendaftaran.get_pendaftaran
    monkeypatch.setattr(pendaftaran, "get_pendaftaran", lambda d, n: {**real(d, n), "klaim_asuransi": []})
    assert client.post("/api/pendaftaran/1/klaim").status_code == 409
    assert len(db.pendaftaran.find_one({"no_registrasi": "1"})["klaim_asuransi"]) == 1


def test_nik_is_unique_after_ensure_indexes(db, monkeypatch):
    import pytest
    from pymongo.errors import DuplicateKeyError
    from app import database
    monkeypatch.setattr(database, "db", db)
    database.ensure_indexes()
    nik = db.pasien.find_one()["nik_pasien"]
    with pytest.raises(DuplicateKeyError):
        db.pasien.insert_one({"nik_pasien": nik})


def test_w09_refusals(client, db):
    assert client.patch("/api/pembayaran/99/status", json={"status": "Berhasil"}).status_code == 404
    assert client.patch("/api/pembayaran/3/status", json={"status": "Gagal"}).status_code == 422
    assert client.patch("/api/pembayaran/3/status", json={}).status_code == 422
    assert db.pembayaran.find_one({"no_billing": "3"})["status_pembayaran"] == "Gagal"
