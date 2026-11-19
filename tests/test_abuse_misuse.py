"""Misuse (a legitimate caller doing it wrong) and abuse (a hostile caller) for every endpoint.

Rules checked everywhere: never a 5xx for bad input, nothing written when the request is refused,
nothing cached for a refused request, no database internals in a response.
"""
import re
from urllib.parse import quote

import pytest
from pymongo.errors import ServerSelectionTimeoutError

from app import cache
from app.main import app
from tests.conftest import FakeRedis

NIK1 = "3171000000000001"
NEW_PATIENT = {
    "nik_pasien": "3202154408970003", "nama_pasien": "Kinanti Larasati", "tanggal_lahir_pasien": "1997-08-04",
    "jenis_kelamin": "P", "jalan": "Jl. Raya 27", "rt": "03", "rw": "05", "kota": "Sukabumi",
    "provinsi": "Jawa Barat", "no_telp_pasien": "085721946318", "id_pegawai": "41",
}
WRITES = {
    "w01": ("POST", "/api/pasien", NEW_PATIENT, set()),
    "w02": ("POST", "/api/pendaftaran/rawat-jalan",
            {"nik_pasien": NIK1, "id_jadwal": "2", "tanggal": "2026-10-06", "id_penjamin": "1", "id_pegawai": "11",
             "jam_daftar": "12:45:00"}, {"jam_daftar"}),
    "w03": ("POST", "/api/pendaftaran/igd", {"nik_pasien": NIK1, "id_pegawai": "11", "id_penjamin": "1"}, {"id_penjamin"}),
    "w04": ("PATCH", "/api/pendaftaran/2/penjamin", {"id_penjamin": "1", "no_kartu": "123"}, set()),
    "w05": ("POST", "/api/pendaftaran/1/admisi",
            {"jenis_upgrade": "0", "catatan_admisi": "Observasi", "id_pegawai": "100", "id_ruangan": "1"}, set()),
    "w06": ("POST", "/api/pelayanan/penanganan-rujukan",
            {"no_registrasi": "1", "id_pegawai": "130", "id_pegawai_peminta": "125", "versi_harga": "2026"}, {"versi_harga"}),
    "w07": ("POST", "/api/pendaftaran/1/penunjang",
            {"jenis": "laboratorium", "id_layanan": "306", "id_unit": "32", "id_pegawai_medis": "125",
             "id_pegawai_paramedis": "360", "versi_harga": "2026", "detail": {"nama_laboratorium": "Lab X"}},
            {"versi_harga", "detail"}),
    "w08": ("POST", "/api/pendaftaran/1/pembayaran", {"metode_pembayaran": "Tunai", "id_pegawai": "70"}, set()),
    "w09": ("PATCH", "/api/pembayaran/3/status", {"status": "Berhasil"}, set()),
}
GETS = [
    "/api/pasien?nik=3171000000000001", "/api/pasien/1/riwayat-medis", "/api/pasien/empat-layanan",
    "/api/pendaftaran/1/layanan", "/api/jadwal-dokter/kuota?tanggal=2026-10-05", "/api/ruangan/tersedia",
    "/api/penunjang/rekap-harian?dari=2026-10-08&sampai=2026-10-09",
    "/api/laporan/pendapatan-bulanan?tahun=2026&bulan=10", "/api/laporan/klaim-penjamin",
    "/api/laporan/layanan-terpopuler?tanggal_acuan=2026-11-19",
]
HOSTILE_IDS = ["../../etc/passwd", "1' OR '1'='1", '{"$gt": ""}', "\x00", "9" * 5000, "１２３", "😀", "1;DROP TABLE x",
               "null", "-1", "%", "*"]


def unpay(db):
    """The seed visit 1 is already paid; make it payable again for tests that need a new payment."""
    db.pembayaran.update_many({"no_registrasi": "1"}, {"$set": {"status_pembayaran": "Gagal"}})


def snap(db):
    return {name: db[name].count_documents({}) for name in sorted(db.list_collection_names())}


def contains_key(obj, key):
    if isinstance(obj, dict):
        return key in obj or any(contains_key(v, key) for v in obj.values())
    if isinstance(obj, list):
        return any(contains_key(v, key) for v in obj)
    return False


def test_every_endpoint_refuses_the_wrong_http_method(client):
    paths = {p: ops for p, ops in app.openapi()["paths"].items() if p.startswith("/api/") and p != "/api/unit-layanan"}
    assert sum(len(ops) for ops in paths.values()) == 20
    for path, ops in paths.items():
        allowed = {m.upper() for m in ops}
        url = re.sub(r"\{[^}]+\}", "1", path)
        for method in {"GET", "POST", "PATCH", "PUT", "DELETE"} - allowed:
            assert client.request(method, url).status_code == 405, (method, url)


def test_unknown_routes_are_404(client):
    for path in ("/api/nope", "/api/pasien/1/2/3", "/api/pendaftaran", "/api/pembayaran/1", "/admin", "/.env",
                 "/api/pasien/../../etc/passwd"):
        assert client.get(path).status_code in (404, 405), path


@pytest.mark.parametrize("name", WRITES)
@pytest.mark.parametrize("raw", [b"", b"null", b"[]", b'"text"', b"{bad json", b"{}", b"\xff\xfe"])
def test_body_that_is_not_a_proper_object_is_422(client, db, name, raw):
    method, url, _, _ = WRITES[name]
    before = snap(db)
    r = client.request(method, url, content=raw, headers={"content-type": "application/json"})
    assert r.status_code == 422
    assert snap(db) == before


@pytest.mark.parametrize("name", WRITES)
def test_form_data_and_plain_text_instead_of_json(client, db, name):
    method, url, body, _ = WRITES[name]
    before = snap(db)
    assert client.request(method, url, data={"a": "b"}).status_code == 422
    assert client.request(method, url, content="not json", headers={"content-type": "text/plain"}).status_code == 422
    assert snap(db) == before


@pytest.mark.parametrize("name", WRITES)
def test_each_required_field_missing_is_422(client, db, name):
    method, url, body, optional = WRITES[name]
    before = snap(db)
    for field in set(body) - optional:
        partial = {k: v for k, v in body.items() if k != field}
        assert client.request(method, url, json=partial).status_code == 422, field
    assert snap(db) == before


@pytest.mark.parametrize("name", WRITES)
def test_wrong_type_for_each_field_is_422(client, db, name):
    method, url, body, _ = WRITES[name]
    before = snap(db)
    for field in body:
        values = [5, ["x"], True] if field == "detail" else [5, 1.5, ["x"], {"$ne": ""}, True]
        for bad in values:
            r = client.request(method, url, json={**body, field: bad})
            assert r.status_code == 422, (field, bad, r.text)
    assert snap(db) == before


def test_whitespace_only_text_is_refused(client, db):
    before = snap(db)
    assert client.post("/api/pasien", json={**NEW_PATIENT, "nama_pasien": "   "}).status_code == 422
    assert client.post("/api/pendaftaran/1/admisi", json={**WRITES["w05"][2], "catatan_admisi": " \t "}).status_code == 422
    assert snap(db) == before


def test_bad_formats_in_a_new_patient_are_refused(client, db):
    before = snap(db)
    for field, bad in [("nik_pasien", "123"), ("nik_pasien", "abcdefghijklmnop"), ("nik_pasien", "3202154408970003x"),
                       ("tanggal_lahir_pasien", "04-08-1997"), ("tanggal_lahir_pasien", "2999-01-01"),
                       ("tanggal_lahir_pasien", "1800-01-01"), ("tanggal_lahir_pasien", "tidak tahu"),
                       ("jenis_kelamin", "l"), ("jenis_kelamin", "Pria"), ("rt", "abcd"), ("rw", "-1"),
                       ("no_telp_pasien", "call me"), ("no_telp_pasien", "1"), ("id_pegawai", "41; drop"),
                       ("id_pegawai", "-4")]:
        assert client.post("/api/pasien", json={**NEW_PATIENT, field: bad}).status_code == 422, (field, bad)
    assert snap(db) == before


def test_bad_formats_in_visit_and_other_bodies_are_refused(client, db):
    before = snap(db)
    rj = WRITES["w02"][2]
    for field, bad in [("jam_daftar", "25:00"), ("jam_daftar", "12:61"), ("jam_daftar", "noon"), ("id_jadwal", "x"),
                       ("id_jadwal", "1.5"), ("id_penjamin", "-1")]:
        assert client.post("/api/pendaftaran/rawat-jalan", json={**rj, field: bad}).status_code == 422, (field, bad)
    assert client.patch("/api/pendaftaran/2/penjamin", json={"id_penjamin": "1", "no_kartu": "a b"}).status_code == 422
    assert client.post("/api/pendaftaran/1/admisi", json={**WRITES["w05"][2], "jenis_upgrade": "2"}).status_code == 422
    assert client.post("/api/pelayanan/penanganan-rujukan",
                       json={**WRITES["w06"][2], "versi_harga": "20"}).status_code == 422
    assert snap(db) == before


def test_missing_or_empty_search_is_refused(client):
    assert client.get("/api/pasien", params={"nik": "", "nama": ""}).status_code == 422
    assert client.get("/api/pasien", params={"unknown": "x"}).status_code == 422


def test_pay_twice_after_success_is_refused_but_retry_after_failure_is_allowed(client, db):
    unpay(db)
    pay = {"metode_pembayaran": "Tunai", "id_pegawai": "70"}
    first = client.post("/api/pendaftaran/1/pembayaran", json=pay)
    assert first.status_code == 201
    assert client.post("/api/pendaftaran/1/pembayaran", json=pay).status_code == 201
    assert client.patch(f"/api/pembayaran/{first.json()['no_billing']}/status", json={"status": "Berhasil"}).status_code == 200
    again = client.post("/api/pendaftaran/1/pembayaran", json=pay)
    assert again.status_code == 409 and "sudah dibayar" in again.json()["detail"]
    assert db.pembayaran.count_documents({"no_registrasi": "1"}) == 4


def test_marking_successful_twice_is_harmless(client, db):
    for _ in range(2):
        assert client.patch("/api/pembayaran/3/status", json={"status": "Berhasil"}).status_code == 200
    assert db.pembayaran.find_one({"no_billing": "3"})["status_pembayaran"] == "Berhasil"


@pytest.mark.parametrize("nama", [".*", "(a+)+$", "[", "\\", "Bud.", "B.di", "^", "$", "%", "(?i)budi", "a|b", "{1,2}"])
def test_regex_characters_in_name_search_are_literal(client, nama):
    r = client.get("/api/pasien", params={"nama": nama})
    assert r.status_code == 200
    assert r.json() == {"data": []}


@pytest.mark.parametrize("value", ['{"$ne": null}', '{"$gt": ""}', "[]", "' || '1'=='1", "$where: 1"])
def test_operator_strings_in_search_params_match_nothing(client, value):
    for key in ("nik", "nama"):
        r = client.get("/api/pasien", params={key: value})
        assert r.status_code == 200 and r.json() == {"data": []}


def test_bracket_operator_syntax_in_query_string_is_ignored(client):
    assert client.get("/api/pasien?nik[$ne]=x").status_code == 422
    assert client.get("/api/pasien?nik[$regex]=.*&nama[$ne]=x").status_code == 422


@pytest.mark.parametrize("name", [n for n in WRITES if n != "w09"])
def test_operator_objects_in_ids_are_refused(client, db, name):
    method, url, body, _ = WRITES[name]
    before = snap(db)
    for field in body:
        if field.startswith("id_") or field == "nik_pasien":
            for bad in ({"$ne": ""}, {"$gt": ""}, ["1"], "1 OR 1=1"):
                assert client.request(method, url, json={**body, field: bad}).status_code == 422, (field, bad)
    assert snap(db) == before


@pytest.mark.parametrize("hostile", HOSTILE_IDS)
def test_hostile_ids_in_the_path_are_404_everywhere(client, db, hostile):
    before = snap(db)
    seg = quote(hostile, safe="")
    assert client.get(f"/api/pendaftaran/{seg}/layanan").status_code == 404
    assert client.get(f"/api/pasien/{seg}/riwayat-medis").status_code == 404
    assert client.patch(f"/api/pendaftaran/{seg}/penjamin", json=WRITES["w04"][2]).status_code == 404
    assert client.post(f"/api/pendaftaran/{seg}/admisi", json=WRITES["w05"][2]).status_code == 404
    assert client.post(f"/api/pendaftaran/{seg}/penunjang", json=WRITES["w07"][2]).status_code == 404
    assert client.post(f"/api/pendaftaran/{seg}/pembayaran", json=WRITES["w08"][2]).status_code == 404
    assert client.post(f"/api/pendaftaran/{seg}/klaim").status_code == 404
    assert client.patch(f"/api/pembayaran/{seg}/status", json={"status": "Berhasil"}).status_code == 404
    assert snap(db) == before


def test_oversized_input_is_refused(client, db):
    before = snap(db)
    assert client.get("/api/pasien", params={"nama": "a" * 101}).status_code == 422
    assert client.get("/api/pasien", params={"nik": "1" * 101}).status_code == 422
    assert client.post("/api/pasien", json={**NEW_PATIENT, "nama_pasien": "x" * 201}).status_code == 422
    assert client.post("/api/pasien", json={**NEW_PATIENT, "nama_pasien": "x" * 1_000_000}).status_code == 422
    body = WRITES["w07"][2]
    assert client.post("/api/pendaftaran/1/penunjang",
                       json={**body, "detail": {f"k{i}": "v" for i in range(11)}}).status_code == 422
    assert client.post("/api/pendaftaran/1/penunjang",
                       json={**body, "detail": {"nama_laboratorium": "x" * 201}}).status_code == 422
    assert client.post("/api/pendaftaran/1/penunjang",
                       json={**body, "detail": {"k" * 51: "v"}}).status_code == 422
    assert client.post("/api/pendaftaran/1/penunjang",
                       json={**body, "detail": {"nama_laboratorium": {"nested": {"$ne": 1}}}}).status_code == 422
    assert client.post("/api/pendaftaran/1/penunjang",
                       json={**body, "detail": {"nama_laboratorium": ["a"]}}).status_code == 422
    assert snap(db) == before


def test_nul_characters_are_refused(client, db):
    before = snap(db)
    assert client.get("/api/pasien", params={"nama": "a\x00b"}).status_code == 422
    assert client.get("/api/pasien", params={"nik": "a\x00b"}).status_code == 422
    for field in ("nama_pasien", "jalan", "kota", "provinsi"):
        assert client.post("/api/pasien", json={**NEW_PATIENT, field: "a\x00b"}).status_code == 422, field
    assert snap(db) == before


BAD_DATES = ["9999-12-31", "0001-01-01", "2026-13-45", "2026-02-30", "1999-12-31", "2101-01-01", "abc",
             "2026-10-05T00:00:00", "'; drop", "2026/10/05", "05-10-2026", "-2026-10-05"]


@pytest.mark.parametrize("bad", BAD_DATES)
def test_extreme_or_malformed_dates_are_422_not_500(client, db, redis, bad):
    before, cached = snap(db), dict(redis.store)
    assert client.get("/api/jadwal-dokter/kuota", params={"tanggal": bad}).status_code == 422
    assert client.get("/api/penunjang/rekap-harian", params={"dari": bad, "sampai": "2026-10-09"}).status_code == 422
    assert client.get("/api/penunjang/rekap-harian", params={"dari": "2026-10-08", "sampai": bad}).status_code == 422
    assert client.get("/api/laporan/layanan-terpopuler", params={"tanggal_acuan": bad}).status_code == 422
    assert client.post("/api/pendaftaran/rawat-jalan", json={**WRITES["w02"][2], "tanggal": bad}).status_code == 422
    assert snap(db) == before and redis.store == cached


def test_report_range_is_capped(client):
    assert client.get("/api/penunjang/rekap-harian",
                      params={"dari": "2000-01-01", "sampai": "2100-01-01"}).status_code == 422
    assert client.get("/api/penunjang/rekap-harian",
                      params={"dari": "2026-01-01", "sampai": "2027-01-03"}).status_code == 422
    assert client.get("/api/penunjang/rekap-harian",
                      params={"dari": "2026-01-01", "sampai": "2027-01-02"}).status_code == 200


@pytest.mark.parametrize("tahun", ["-1", "0", "1999", "2101", "abc", "99999999999999999999", "1e3", "2026.5", ""])
def test_bad_year_is_422(client, tahun):
    assert client.get("/api/laporan/pendapatan-bulanan", params={"tahun": tahun, "bulan": 10}).status_code == 422


@pytest.mark.parametrize("bulan", ["0", "13", "-1", "x", "99999999999999999999", "1.5", ""])
def test_bad_month_is_422(client, bulan):
    assert client.get("/api/laporan/pendapatan-bulanan", params={"tahun": 2026, "bulan": bulan}).status_code == 422


@pytest.mark.parametrize("n", ["0", "25", "-5", "x", "99999999999999999999", "2.5", ""])
def test_bad_month_window_is_422(client, n):
    assert client.get("/api/laporan/layanan-terpopuler", params={"bulan_terakhir": n}).status_code == 422


def test_equivalent_date_spellings_share_one_cache_entry(client, redis):
    first = client.get("/api/laporan/layanan-terpopuler", params={"tanggal_acuan": "2026-11-19"}).json()
    second = client.get("/api/laporan/layanan-terpopuler", params={"tanggal_acuan": "20261119"}).json()
    assert first["source"] == "mongodb" and second["source"] == "redis"
    assert len([k for k in redis.store if "layanan-terpopuler" in k and ":v" in k]) == 1


def test_client_cannot_choose_ids_or_inject_fields_when_registering_a_patient(client, db):
    body = {**NEW_PATIENT, "no_rm": "999", "_id": "deadbeef", "id_penjamin": "1", "status": "Aktif",
            "nomor_telepon": [{"no_telp_pasien": "666"}], "klaim_asuransi": [{"x": 1}]}
    r = client.post("/api/pasien", json=body)
    assert r.status_code == 201 and r.json()["no_rm"] == "3"
    patient = db.pasien.find_one({"nik_pasien": NEW_PATIENT["nik_pasien"]})
    assert patient["no_rm"] == "3" and patient["nomor_telepon"] == [{"no_telp_pasien": "085721946318"}]
    assert "klaim_asuransi" not in patient and str(patient["_id"]) != "deadbeef"
    assert db.daftar_penjaminan.find_one({"nik_pasien": NEW_PATIENT["nik_pasien"]})["id_penjamin"] == "3"
    assert db.rme.find_one({"no_rm": "999"}) is None


def test_client_cannot_set_payment_amount_or_status(client, db):
    unpay(db)
    r = client.post("/api/pendaftaran/1/pembayaran", json={
        "metode_pembayaran": "Tunai", "id_pegawai": "70", "jumlah_pembayaran": "1.00",
        "status_pembayaran": "Berhasil", "no_billing": "1", "tanggal_pembayaran": "1999-01-01"})
    assert r.status_code == 201
    doc = db.pembayaran.find_one({"no_billing": "5"})
    assert doc["jumlah_pembayaran"] == "1300000.00" and doc["status_pembayaran"] == "Gagal"
    assert doc["tanggal_pembayaran"] != "1999-01-01"
    assert db.pembayaran.find_one({"no_billing": "1"})["jumlah_pembayaran"] == "1250000.00"


def test_status_update_cannot_change_other_fields(client, db):
    client.patch("/api/pembayaran/3/status", json={"status": "Berhasil", "jumlah_pembayaran": "1.00",
                                                    "no_registrasi": "1", "metode_pembayaran": "Kartu"})
    doc = db.pembayaran.find_one({"no_billing": "3"})
    assert (doc["jumlah_pembayaran"], doc["no_registrasi"], doc["metode_pembayaran"]) == ("150000.00", "2", "Tunai")


def test_igd_registration_cannot_pose_as_another_visit_type(client, db):
    r = client.post("/api/pendaftaran/igd", json={"nik_pasien": NIK1, "id_pegawai": "11", "jenis_tindakan": "Rawat_Jalan",
                                                   "hasil_penanganan": "Pulang", "klaim_asuransi": [{"x": 1}]})
    assert r.status_code == 201
    visit = db.pendaftaran.find_one({"no_registrasi": r.json()["no_registrasi"]})
    assert visit["jenis_tindakan"] == "IGD" and visit["hasil_penanganan"] is None and visit["klaim_asuransi"] == []


def test_support_request_cannot_write_arbitrary_fields(client, db):
    body = {**WRITES["w07"][2], "detail": {"nama_laboratorium": "Lab X", "hasil_laboratorium": "HACKED",
                                           "id_pegawai": "1", "$set": "x", "status_kebutuhan": "Selesai"}}
    assert client.post("/api/pendaftaran/1/penunjang", json=body).status_code == 201
    doc = db.penunjang_medis.find_one({"id_pelayanan_medis": "9"})
    assert doc["status_kebutuhan"] == "Diproses"
    assert doc["laboratorium"]["id_pegawai"] == "360"
    assert "$set" not in doc["laboratorium"] and doc["laboratorium"]["hasil_laboratorium"] is None


def test_replayed_writes_do_not_duplicate(client, db):
    before = snap(db)
    assert client.post("/api/pasien", json=NEW_PATIENT).status_code == 201
    assert client.post("/api/pasien", json=NEW_PATIENT).status_code == 409
    assert db.pasien.count_documents({"nik_pasien": NEW_PATIENT["nik_pasien"]}) == 1
    assert client.post("/api/pendaftaran/1/admisi", json=WRITES["w05"][2]).status_code == 201
    assert client.post("/api/pendaftaran/1/admisi", json=WRITES["w05"][2]).status_code == 409
    assert db.admisi.count_documents({"no_registrasi": "1"}) == 1
    db.daftar_penjaminan.insert_one({"nik_pasien": "3171000000000002", "id_penjamin": "2", "no_kartu": "9", "status": "Aktif"})
    assert client.post("/api/pendaftaran/3/klaim").status_code == 201
    assert client.post("/api/pendaftaran/3/klaim").status_code == 409
    assert len(db.pendaftaran.find_one({"no_registrasi": "3"})["klaim_asuransi"]) == 1
    assert client.patch("/api/pendaftaran/2/penjamin", json=WRITES["w04"][2]).status_code == 200
    assert client.patch("/api/pendaftaran/2/penjamin", json=WRITES["w04"][2]).status_code == 409
    assert db.daftar_penjaminan.count_documents({"nik_pasien": "3171000000000002", "id_penjamin": "1"}) == 1
    assert snap(db)["pasien"] == before["pasien"] + 1


def test_failed_write_never_reuses_an_id(client, db, monkeypatch):
    real = type(db.pasien).insert_one

    def flaky(self, doc, *a, **k):
        if self.name == "pasien":
            raise RuntimeError("boom")
        return real(self, doc, *a, **k)

    monkeypatch.setattr(type(db.pasien), "insert_one", flaky)
    assert client.post("/api/pasien", json=NEW_PATIENT).status_code == 503
    monkeypatch.undo()
    assert client.post("/api/pasien", json=NEW_PATIENT).json()["no_rm"] == "4"
    assert db.rme.count_documents({"no_rm": "3"}) == 0


def test_search_never_returns_more_than_50_patients(client, db):
    db.pasien.insert_many([{"nik_pasien": f"{i:016d}", "no_rm": str(100 + i), "nama_pasien": f"Zed {i}",
                            "nomor_telepon": []} for i in range(60)])
    assert len(client.get("/api/pasien", params={"nama": "zed"}).json()["data"]) == 50


@pytest.mark.parametrize("url", GETS)
def test_responses_never_contain_database_ids(client, url):
    r = client.get(url)
    assert r.status_code == 200 and not contains_key(r.json(), "_id")


def test_write_responses_do_not_leak_database_ids(client, db):
    unpay(db)
    for name in ("w01", "w03", "w08"):
        method, url, body, _ = WRITES[name]
        r = client.request(method, url, json=body)
        assert r.status_code in (200, 201) and not contains_key(r.json(), "_id"), name


def test_validation_errors_do_not_echo_server_internals(client):
    text = client.post("/api/pasien", json={"nik_pasien": "x"}).text.lower()
    for leak in ("traceback", "pymongo", "mongomock", "/nix/store", "simrs"):
        assert leak not in text


def test_database_down_is_a_clean_503_everywhere(client, db, monkeypatch):
    def down(*a, **k):
        raise ServerSelectionTimeoutError("mongodb://secret-host:27017 unreachable")

    cls = type(db.pasien)
    for method in ("find", "find_one", "count_documents", "insert_one", "update_one", "aggregate",
                   "find_one_and_update", "delete_one"):
        monkeypatch.setattr(cls, method, down)

    calls = [("GET", "/api/pasien?nik=1", None), ("GET", "/api/ruangan/tersedia", None),
             ("GET", "/api/laporan/layanan-terpopuler", None), ("GET", "/api/pasien/1/riwayat-medis", None),
             ("GET", "/api/pasien/empat-layanan", None), ("GET", "/api/pendaftaran/1/layanan", None),
             ("POST", "/api/pasien", NEW_PATIENT), ("POST", "/api/pendaftaran/igd", WRITES["w03"][2]),
             ("PATCH", "/api/pembayaran/3/status", {"status": "Berhasil"}),
             ("POST", "/api/pendaftaran/1/klaim", None)]
    for method, url, body in calls:
        r = client.request(method, url, json=body)
        assert r.status_code == 503, (method, url)
        assert r.json() == {"detail": "database tidak tersedia"}
        assert "secret-host" not in r.text


def test_redis_failing_does_not_break_any_endpoint(client, db, monkeypatch):
    class Broken(FakeRedis):
        def get(self, key):
            raise ConnectionError("redis down")

        def set(self, key, value, ex=None):
            raise ConnectionError("redis down")

        def incr(self, key):
            raise ConnectionError("redis down")

        def delete(self, *keys):
            raise ConnectionError("redis down")

    monkeypatch.setattr(cache, "redis", Broken())
    for url in GETS:
        assert client.get(url).status_code == 200, url
    assert client.get("/api/laporan/klaim-penjamin").json()["source"] == "mongodb"
    assert client.post("/api/pendaftaran/1/penunjang", json=WRITES["w07"][2]).status_code == 201
    assert client.patch("/api/pembayaran/3/status", json={"status": "Berhasil"}).status_code == 200


def test_endpoints_work_when_redis_is_not_configured(client, monkeypatch):
    monkeypatch.setattr(cache, "redis", None)
    for url in GETS:
        assert client.get(url).status_code == 200, url
