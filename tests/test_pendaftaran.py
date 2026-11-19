from datetime import date

NIK1 = "3171000000000001"
NIK2 = "3171000000000002"


def rj(**over):
    return {"nik_pasien": NIK1, "id_jadwal": "2", "tanggal": "2026-10-06", "id_penjamin": "1",
            "id_pegawai": "11", "jam_daftar": "12:45:00", **over}


def test_s04_support_services_of_a_visit(client):
    r = client.get("/api/pendaftaran/1/layanan")
    assert r.status_code == 200
    assert r.json()["data"] == [{"jenis_layanan": "Laboratorium", "no_registrasi": "1", "nama_layanan": "Hematologi",
                                 "ruang_unit": "Laboratorium", "nama_petugas": "Lab Man"}]
    assert [x["jenis_layanan"] for x in client.get("/api/pendaftaran/3/layanan").json()["data"]] == ["Farmasi"]


def test_s04_unknown_visit_is_404_and_visit_without_support_is_empty(client, db):
    assert client.get("/api/pendaftaran/99/layanan").status_code == 404
    db.penunjang_medis.delete_many({})
    assert client.get("/api/pendaftaran/1/layanan").json() == {"data": []}


def test_s04_fills_master_cache(client, redis):
    client.get("/api/pendaftaran/1/layanan")
    assert {"simrs:master:layanan", "simrs:master:unit_layanan", "simrs:master:pegawai"} <= set(redis.store)


def test_w02_registers_when_quota_is_left(client, db):
    r = client.post("/api/pendaftaran/rawat-jalan", json=rj())
    assert r.status_code == 201
    assert r.json() == {"no_registrasi": "4", "tanggal_daftar": "2026-10-06"}
    visit = db.pendaftaran.find_one({"no_registrasi": "4"})
    assert visit["jenis_tindakan"] == "Rawat_Jalan" and visit["hasil_penanganan"] is None
    assert visit["jam_daftar"] == "12:45:00" and visit["klaim_asuransi"] == []
    assert db.rawat_jalan.find_one({"no_registrasi": "4"}) is not None


def test_w02_refuses_full_quota_wrong_day_and_unknown_things(client, db):
    full = client.post("/api/pendaftaran/rawat-jalan", json=rj(id_jadwal="1", tanggal="2026-10-05"))
    assert full.status_code == 409 and "kuota" in full.json()["detail"]
    assert client.post("/api/pendaftaran/rawat-jalan", json=rj(id_jadwal="1")).status_code == 409
    assert client.post("/api/pendaftaran/rawat-jalan", json=rj(id_jadwal="9")).status_code == 404
    assert client.post("/api/pendaftaran/rawat-jalan", json=rj(nik_pasien="9999999999999999")).status_code == 404
    assert client.post("/api/pendaftaran/rawat-jalan", json=rj(id_penjamin="9")).status_code == 404
    assert client.post("/api/pendaftaran/rawat-jalan", json=rj(tanggal="besok")).status_code == 422
    assert db.pendaftaran.count_documents({}) == 3


def test_w02_igd_visit_does_not_use_outpatient_quota(client):
    assert client.post("/api/pendaftaran/rawat-jalan", json=rj()).status_code == 201


def test_w03_igd_defaults_to_umum_guarantor(client, db):
    r = client.post("/api/pendaftaran/igd", json={"nik_pasien": NIK1, "id_pegawai": "11"})
    assert r.status_code == 201 and r.json() == {"no_registrasi": "4", "id_penjamin": "3"}
    visit = db.pendaftaran.find_one({"no_registrasi": "4"})
    assert visit["jenis_tindakan"] == "IGD" and visit["tanggal_daftar"] == date.today().isoformat()
    assert db.igd.find_one({"no_registrasi": "4"}) is not None


def test_w03_unknown_patient_is_404_and_ids_increase(client, db):
    unknown = {"nik_pasien": "9999999999999999", "id_pegawai": "11"}
    assert client.post("/api/pendaftaran/igd", json=unknown).status_code == 404
    client.post("/api/pendaftaran/igd", json={"nik_pasien": NIK1, "id_pegawai": "11", "id_penjamin": "2"})
    r = client.post("/api/pendaftaran/igd", json={"nik_pasien": NIK1, "id_pegawai": "11"})
    assert r.json()["no_registrasi"] == "5"
    assert db.pendaftaran.find_one({"no_registrasi": "4"})["id_penjamin"] == "2"


def test_w04_records_guarantor_and_fixes_igd_visit(client, db):
    r = client.patch("/api/pendaftaran/2/penjamin", json={"id_penjamin": "1", "no_kartu": "0002318475906"})
    assert r.status_code == 200
    assert db.pendaftaran.find_one({"no_registrasi": "2"})["id_penjamin"] == "1"
    dp = db.daftar_penjaminan.find_one({"nik_pasien": NIK2, "id_penjamin": "1"})
    assert dp["no_kartu"] == "0002318475906" and dp["status"] == "Aktif"


def test_w04_refusals(client, db):
    body = {"id_penjamin": "1", "no_kartu": "1"}
    assert client.patch("/api/pendaftaran/1/penjamin", json=body).status_code == 409
    assert client.patch("/api/pendaftaran/99/penjamin", json=body).status_code == 404
    assert client.patch("/api/pendaftaran/2/penjamin", json={"id_penjamin": "9", "no_kartu": "1"}).status_code == 404
    assert client.patch("/api/pendaftaran/2/penjamin", json=body).status_code == 200
    assert client.patch("/api/pendaftaran/2/penjamin", json=body).status_code == 409
    assert db.daftar_penjaminan.count_documents({"nik_pasien": NIK2}) == 1


def admisi(room, **over):
    return {"jenis_upgrade": "0", "catatan_admisi": "Observasi", "id_pegawai": "100", "id_ruangan": room, **over}


def test_w05_admits_into_room_with_space(client, db):
    r = client.post("/api/pendaftaran/1/admisi", json=admisi("1"))
    assert r.status_code == 201
    assert db.admisi.find_one({"no_registrasi": "1"})["catatan_admisi"] == "Observasi"
    open_stay = db.penempatan_ruangan.find_one({"no_registrasi": "1", "id_ruangan": "1", "waktu_keluar": None,
                                                "waktu_masuk": {"$gt": "2026-10-05 12:00:01"}})
    assert open_stay is not None


def test_w05_refusals_write_nothing(client, db):
    before = db.penempatan_ruangan.count_documents({})
    assert client.post("/api/pendaftaran/1/admisi", json=admisi("2")).status_code == 409
    assert client.post("/api/pendaftaran/1/admisi", json=admisi("3")).status_code == 409
    assert client.post("/api/pendaftaran/1/admisi", json=admisi("4")).status_code == 409
    assert client.post("/api/pendaftaran/1/admisi", json=admisi("9")).status_code == 404
    assert client.post("/api/pendaftaran/99/admisi", json=admisi("1")).status_code == 404
    assert db.admisi.count_documents({}) == 0 and db.penempatan_ruangan.count_documents({}) == before


def test_w05_second_admission_and_room_filling_up(client):
    assert client.post("/api/pendaftaran/1/admisi", json=admisi("1")).status_code == 201
    assert client.post("/api/pendaftaran/1/admisi", json=admisi("1")).status_code == 409
    assert client.post("/api/pendaftaran/3/admisi", json=admisi("1")).status_code == 409


def pen(**over):
    return {"jenis": "laboratorium", "id_layanan": "306", "id_unit": "32", "id_pegawai_medis": "125",
            "id_pegawai_paramedis": "360", "detail": {"nama_laboratorium": "Lab X", "jenis_pemeriksaan": "Urin"}, **over}


def test_w07_lab_request_is_embedded_and_in_its_own_collection(client, db):
    r = client.post("/api/pendaftaran/1/penunjang", json=pen())
    assert r.status_code == 201 and r.json()["id_pelayanan_medis"] == "9"
    service = db.pelayanan_medis.find_one({"id_pelayanan_medis": "9"})
    assert service["waktu_selesai"] is None and service["versi_harga"] == "2026" and service["id_unit"] == "32"
    doc = db.penunjang_medis.find_one({"id_pelayanan_medis": "9"})
    assert doc["status_kebutuhan"] == "Diproses" and doc["tanggal_permintaan"] == date.today().isoformat()
    assert doc["laboratorium"] == {"nama_laboratorium": "Lab X", "jenis_pemeriksaan": "Urin",
                                   "hasil_laboratorium": None, "id_pegawai": "360"}
    assert doc["radiologi"] is None and doc["farmasi"] is None and doc["gizi"] is None
    assert db.laboratorium.find_one({"id_pelayanan_medis": "9"})["jenis_pemeriksaan"] == "Urin"


def test_w07_other_types(client, db):
    client.post("/api/pendaftaran/1/penunjang", json=pen(jenis="gizi", detail={"jenis_diet": "Rendah garam",
                                                                               "id_pegawai_koki": "11"}))
    gizi = db.penunjang_medis.find_one({"id_pelayanan_medis": "9"})["gizi"]
    assert gizi["jenis_diet"] == "Rendah garam" and gizi["id_pegawai_koki"] == "11" and gizi["id_pegawai"] == "360"
    client.post("/api/pendaftaran/1/penunjang", json=pen(jenis="farmasi", detail={}))
    assert db.penunjang_medis.find_one({"id_pelayanan_medis": "10"})["farmasi"] == {
        "laporan_transaksi_obat": None, "id_pegawai": "360"}


def test_w07_refusals(client, db):
    assert client.post("/api/pendaftaran/99/penunjang", json=pen()).status_code == 404
    assert client.post("/api/pendaftaran/1/penunjang", json=pen(id_layanan="9")).status_code == 404
    assert client.post("/api/pendaftaran/1/penunjang", json=pen(id_unit="9")).status_code == 404
    assert client.post("/api/pendaftaran/1/penunjang", json=pen(versi_harga="1999")).status_code == 409
    assert client.post("/api/pendaftaran/1/penunjang", json=pen(jenis="mri")).status_code == 422
    assert db.pelayanan_medis.count_documents({}) == 8


def test_w07_failure_after_first_insert_is_undone(client, db, monkeypatch):
    real = type(db.penunjang_medis).insert_one

    def flaky(self, doc, *a, **k):
        if self.name == "penunjang_medis":
            raise RuntimeError("boom")
        return real(self, doc, *a, **k)

    monkeypatch.setattr(type(db.penunjang_medis), "insert_one", flaky)
    assert client.post("/api/pendaftaran/1/penunjang", json=pen()).status_code == 503
    monkeypatch.undo()
    assert db.pelayanan_medis.count_documents({}) == 8


def test_w08_visit_that_is_already_paid_is_refused(client, db):
    r = client.post("/api/pendaftaran/1/pembayaran", json={"metode_pembayaran": "Tunai", "id_pegawai": "70"})
    assert r.status_code == 409 and "sudah dibayar" in r.json()["detail"]
    assert db.pembayaran.count_documents({}) == 4


def test_w08_payment_sums_finished_services_and_starts_as_gagal(client, db):
    db.pembayaran.update_many({"no_registrasi": "1"}, {"$set": {"status_pembayaran": "Gagal"}})
    r = client.post("/api/pendaftaran/1/pembayaran", json={"metode_pembayaran": "Non-Tunai", "id_pegawai": "70"})
    assert r.status_code == 201
    assert r.json() == {"no_billing": "5", "jumlah_pembayaran": "1300000.00", "status_pembayaran": "Gagal"}
    doc = db.pembayaran.find_one({"no_billing": "5"})
    assert doc["no_registrasi"] == "1" and doc["status_pembayaran"] == "Gagal"
    assert doc["tanggal_pembayaran"] == date.today().isoformat()


def test_w08_refusals(client, db):
    ok = {"metode_pembayaran": "Tunai", "id_pegawai": "70"}
    assert client.post("/api/pendaftaran/2/pembayaran", json=ok).status_code == 409
    assert client.post("/api/pendaftaran/99/pembayaran", json=ok).status_code == 404
    assert client.post("/api/pendaftaran/1/pembayaran", json={**ok, "metode_pembayaran": "Kartu"}).status_code == 422
    assert db.pembayaran.count_documents({}) == 4


def test_w10_claim_for_insured_visit(client, db):
    db.daftar_penjaminan.insert_one({"nik_pasien": NIK2, "id_penjamin": "2", "no_kartu": "9", "status": "Aktif"})
    r = client.post("/api/pendaftaran/3/klaim")
    assert r.status_code == 201 and r.json() == {"no_registrasi": "3", "id_asuransi": "2"}
    [claim] = db.pendaftaran.find_one({"no_registrasi": "3"})["klaim_asuransi"]
    assert claim == {"id_asuransi": "2", "laporan_rumah_sakit": "Resume medis kunjungan 3",
                     "rincian_klaim_asuransi": "Klaim INA-CBG, status Diajukan"}


def test_w10_refusals(client, db):
    assert client.post("/api/pendaftaran/1/klaim").status_code == 409
    assert client.post("/api/pendaftaran/2/klaim").status_code == 409
    assert client.post("/api/pendaftaran/3/klaim").status_code == 409
    assert client.post("/api/pendaftaran/99/klaim").status_code == 404
    assert db.pendaftaran.find_one({"no_registrasi": "3"})["klaim_asuransi"] == []
