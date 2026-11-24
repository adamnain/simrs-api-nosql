NEW_PATIENT = {
    "nik_pasien": "3202154408970003", "nama_pasien": "Kinanti Larasati", "tanggal_lahir_pasien": "1997-08-04",
    "jenis_kelamin": "P", "jalan": "Jl. Raya 27", "rt": "03", "rw": "05", "kota": "Sukabumi",
    "provinsi": "Jawa Barat", "no_telp_pasien": "085721946318", "id_pegawai": "41",
}


def test_s01_by_nik(client):
    r = client.get("/api/pasien", params={"nik": "3171000000000001"})
    assert r.status_code == 200
    [p] = r.json()["data"]
    assert p["nama_pasien"] == "Budi Santoso"
    assert p["telepon"] == "0811111"
    assert {g["nama_penjamin"] for g in p["penjaminan"]} == {"BPJS Kesehatan", "Umum / Mandiri"}


def test_s01_by_name_is_case_insensitive_and_partial(client):
    r = client.get("/api/pasien", params={"nama": "BUDI"})
    assert {p["nama_pasien"] for p in r.json()["data"]} == {"Budi Santoso", "Ani Budiarti"}


def test_s01_without_filter_is_422_and_unknown_is_empty(client):
    assert client.get("/api/pasien").status_code == 422
    assert client.get("/api/pasien", params={"nik": "0"}).json() == {"data": []}


def test_s05_history(client):
    r = client.get("/api/pasien/1/riwayat-medis")
    assert r.status_code == 200
    [visit] = r.json()["data"]
    assert visit["no_registrasi"] == "1"
    assert visit["jumlah_pelayanan"] == 4
    assert visit["diagnosis"] == ["A09"]
    assert visit["jumlah_entri"] == 2
    assert visit["catatan"] == ["Diberi obat", "Pasien datang"]


def test_s05_unknown_patient_is_404(client):
    assert client.get("/api/pasien/999/riwayat-medis").status_code == 404


def test_s05_patient_without_services_has_zero_counts(client):
    [visit] = [v for v in client.get("/api/pasien/2/riwayat-medis").json()["data"] if v["no_registrasi"] == "2"]
    assert visit["jumlah_pelayanan"] == 2 and visit["diagnosis"] == [] and visit["jumlah_entri"] == 0


def test_s10_only_visit_with_all_four_service_types(client):
    [row] = client.get("/api/pasien/empat-layanan").json()["data"]
    assert row["no_registrasi"] == "1"
    assert (row["penanganan"], row["operasi"], row["perawatan"], row["penunjang"]) == (1, 1, 1, 1)
    assert row["nama_pasien"] == "Budi Santoso"


def test_s10_ignores_non_outpatient_visit(client, db):
    db.pendaftaran.update_one({"no_registrasi": "1"}, {"$set": {"jenis_tindakan": "IGD"}})
    assert client.get("/api/pasien/empat-layanan").json() == {"data": []}


def test_w01_creates_rme_patient_phone_and_guarantor(client, db):
    r = client.post("/api/pasien", json=NEW_PATIENT)
    assert r.status_code == 201
    no_rm = r.json()["no_rm"]
    assert no_rm == "3"
    assert db.rme.find_one({"no_rm": no_rm}) is not None
    p = db.pasien.find_one({"nik_pasien": NEW_PATIENT["nik_pasien"]})
    assert p["nomor_telepon"] == [{"no_telp_pasien": "085721946318"}] and p["no_rm"] == no_rm
    dp = db.daftar_penjaminan.find_one({"nik_pasien": NEW_PATIENT["nik_pasien"]})
    assert dp["id_penjamin"] == "3" and dp["status"] == "Aktif" and dp["no_kartu"] is None


def test_w01_ids_keep_increasing(client):
    client.post("/api/pasien", json=NEW_PATIENT)
    second = dict(NEW_PATIENT, nik_pasien="3202154408970004")
    assert client.post("/api/pasien", json=second).json()["no_rm"] == "4"


def test_w01_duplicate_nik_is_409_and_bad_body_is_422(client, db):
    assert client.post("/api/pasien", json=dict(NEW_PATIENT, nik_pasien="3171000000000001")).status_code == 409
    assert db.rme.count_documents({}) == 2
    assert client.post("/api/pasien", json={"nik_pasien": "1"}).status_code == 422
    assert client.post("/api/pasien", json=dict(NEW_PATIENT, jenis_kelamin="X")).status_code == 422


def test_w01_failure_in_the_middle_removes_earlier_inserts(client, db, monkeypatch):
    real = type(db.pasien).insert_one
    inserted = []

    def flaky(self, doc, *a, **k):
        if self.name == "pasien":
            raise RuntimeError("disk full")
        inserted.append(self.name)
        return real(self, doc, *a, **k)

    monkeypatch.setattr(type(db.pasien), "insert_one", flaky)
    r = client.post("/api/pasien", json=NEW_PATIENT)
    monkeypatch.undo()
    assert r.status_code == 503
    assert inserted == ["rme"]
    assert db.rme.count_documents({}) == 2
    assert db.daftar_penjaminan.count_documents({"nik_pasien": NEW_PATIENT["nik_pasien"]}) == 0
