import mongomock
import pytest
from fastapi.testclient import TestClient

from app import cache
from app.database import get_db
from app.main import app


class FakeRedis:
    """Same calls as upstash_redis.Redis that app/cache.py uses."""

    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value

    def delete(self, *keys):
        for key in keys:
            self.store.pop(key, None)

    def incr(self, key):
        self.store[key] = int(self.store.get(key) or 0) + 1
        return self.store[key]


def sub(name, **fields):
    return {"nama": name, **fields}


def seed(db):
    """A small database in the same shape as seed-data (string ids, embedded arrays)."""
    db.penjamin.insert_many([
        {"id_penjamin": "1", "nama_penjamin": "BPJS Kesehatan", "jenis_penjamin": "JKN", "kontak": []},
        {"id_penjamin": "2", "nama_penjamin": "Asuransi Sehat", "jenis_penjamin": "Asuransi", "kontak": []},
        {"id_penjamin": "3", "nama_penjamin": "Umum / Mandiri", "jenis_penjamin": "Pribadi", "kontak": []},
    ])
    db.pegawai.insert_many([
        {"id_pegawai": "11", "nama": "Rina Admin"},
        {"id_pegawai": "41", "nama": "Tono RM"},
        {"id_pegawai": "70", "nama": "Kiki Kasir"},
        {"id_pegawai": "100", "nama": "Adi Admisi"},
        {"id_pegawai": "125", "nama": "dr. Budi", "tenaga_medis": {"dokter": {"spesialisasi": "Penyakit Dalam"}}},
        {"id_pegawai": "130", "nama": "dr. Sari", "tenaga_medis": {"dokter": {"spesialisasi": "Anak"}}},
        {"id_pegawai": "360", "nama": "Lab Man"},
    ])
    db.rme.insert_many([
        {"no_rm": "1", "id_pegawai": "41", "alergi": [], "riwayat_penyakit": [], "obat_rutin": [], "imunisasi": []},
        {"no_rm": "2", "id_pegawai": "41", "alergi": [], "riwayat_penyakit": [], "obat_rutin": [], "imunisasi": []},
    ])
    db.pasien.insert_many([
        {"nik_pasien": "3171000000000001", "no_rm": "1", "nama_pasien": "Budi Santoso",
         "tanggal_lahir_pasien": "1980-01-02", "jenis_kelamin": "L",
         "nomor_telepon": [{"no_telp_pasien": "0811111"}, {"no_telp_pasien": "0822222"}]},
        {"nik_pasien": "3171000000000002", "no_rm": "2", "nama_pasien": "Ani Budiarti",
         "tanggal_lahir_pasien": "1990-05-06", "jenis_kelamin": "P", "nomor_telepon": []},
    ])
    db.daftar_penjaminan.insert_many([
        {"nik_pasien": "3171000000000001", "id_penjamin": "1", "no_kartu": "000123", "status": "Aktif"},
        {"nik_pasien": "3171000000000001", "id_penjamin": "3", "no_kartu": None, "status": "Aktif"},
    ])
    db.unit_layanan.insert_many([
        {"id_unit": "11", "ruang_unit": "Poli Umum", "departemen": "Rawat Jalan"},
        {"id_unit": "22", "ruang_unit": "Rawat Inap A", "departemen": "Rawat Inap"},
        {"id_unit": "32", "ruang_unit": "Laboratorium", "departemen": "Penunjang"},
    ])
    db.layanan.insert_many([
        {"id_layanan": "63", "nama_layanan": "Konsultasi", "kategori": "Pemeriksaan",
         "tarif": [{"versi_harga": "2025", "harga": "90000.00"}, {"versi_harga": "2026", "harga": "100000.00"}]},
        {"id_layanan": "306", "nama_layanan": "Hematologi", "kategori": "Penunjang",
         "tarif": [{"versi_harga": "2026", "harga": "150000.00"}]},
        {"id_layanan": "70", "nama_layanan": "Operasi Kecil", "kategori": "Tindakan",
         "tarif": [{"versi_harga": "2026", "harga": "1000000.00"}]},
        {"id_layanan": "80", "nama_layanan": "Perawatan Luka", "kategori": "Perawatan",
         "tarif": [{"versi_harga": "2026", "harga": "50000.00"}]},
    ])
    db.penyediaan_layanan.insert_many([
        {"id_unit": "32", "id_layanan": "306"},
        {"id_unit": "11", "id_layanan": "63"},
    ])
    db.jadwal_dokter.insert_many([
        {"id_jadwal": "1", "hari": "Senin", "jam_mulai": "08:00", "jam_selesai": "12:00",
         "kuota": "2", "id_pegawai": "125", "id_unit": "11"},
        {"id_jadwal": "2", "hari": "Selasa", "jam_mulai": "08:00", "jam_selesai": "12:00",
         "kuota": "1", "id_pegawai": "130", "id_unit": "11"},
    ])
    db.pendaftaran.insert_many([
        {"no_registrasi": "1", "tanggal_daftar": "2026-10-05", "jam_daftar": "07:00:00", "jenis_tindakan": "Rawat_Jalan",
         "hasil_penanganan": "Pulang", "nik_pasien": "3171000000000001", "id_penjamin": "1", "id_pegawai": "11",
         "klaim_asuransi": [{"id_asuransi": "1", "laporan_rumah_sakit": "Resume medis kunjungan 1",
                             "rincian_klaim_asuransi": "Klaim INA-CBG, status Diajukan"}]},
        {"no_registrasi": "2", "tanggal_daftar": "2026-10-06", "jam_daftar": "07:00:00", "jenis_tindakan": "IGD",
         "hasil_penanganan": None, "nik_pasien": "3171000000000002", "id_penjamin": "3", "id_pegawai": "11",
         "klaim_asuransi": []},
        {"no_registrasi": "3", "tanggal_daftar": "2026-10-05", "jam_daftar": "07:30:00", "jenis_tindakan": "Rawat_Jalan",
         "hasil_penanganan": None, "nik_pasien": "3171000000000002", "id_penjamin": "2", "id_pegawai": "11",
         "klaim_asuransi": []},
    ])
    db.rawat_jalan.insert_many([{"no_registrasi": "1"}, {"no_registrasi": "3"}])
    db.igd.insert_many([{"no_registrasi": "2"}])

    def pm(i, reg, layanan, unit, mulai, selesai):
        return {"id_pelayanan_medis": i, "no_registrasi": reg, "id_layanan": layanan, "versi_harga": "2026",
                "id_unit": unit, "waktu_mulai": mulai, "waktu_selesai": selesai}

    db.pelayanan_medis.insert_many([
        pm("1", "1", "63", "11", "2026-10-05 08:00:00.000000", "2026-10-05 08:30:00.000000"),
        pm("2", "1", "306", "32", "2026-10-05 09:00:00.000000", "2026-10-05 09:30:00.000000"),
        pm("3", "1", "70", "11", "2026-10-05 10:00:00.000000", "2026-10-05 11:00:00.000000"),
        pm("4", "1", "80", "11", "2026-10-05 11:00:00.000000", "2026-10-05 11:30:00.000000"),
        pm("5", "3", "63", "11", "2026-10-05 10:00:00.000000", "2026-10-05 10:30:00.000000"),
        pm("6", "2", "306", "32", "2026-10-06 09:00:00.000000", None),
        pm("7", "2", "63", "11", "2026-10-06 10:00:00.000000", None),
        pm("8", "3", "306", "32", "2026-10-06 12:00:00.000000", "2026-10-06 12:30:00.000000"),
    ])
    db.penanganan_medis.insert_many([
        {"id_pelayanan_medis": "1", "id_pegawai": "125", "id_pegawai_peminta": "125", "id_jadwal": "1"},
        {"id_pelayanan_medis": "5", "id_pegawai": "125", "id_pegawai_peminta": "125", "id_jadwal": "1"},
        {"id_pelayanan_medis": "7", "id_pegawai": "130", "id_pegawai_peminta": "130", "id_jadwal": "2"},
    ])
    db.operasi.insert_many([{"id_pelayanan_medis": "3", "jenis_operasi": "Kecil", "tim_operasi": []}])
    db.perawatan_klinis.insert_many([{"id_pelayanan_medis": "4", "jenis_perawatan": "Luka", "id_pegawai": "41"}])

    def penunjang(i, tanggal, **types):
        base = {"laboratorium": None, "radiologi": None, "farmasi": None, "gizi": None}
        base.update(types)
        return {"id_pelayanan_medis": i, "laporan_penunjang_medis": None, "tanggal_permintaan": tanggal,
                "status_kebutuhan": "Selesai", "id_pegawai_medis": "125", "id_pegawai_paramedis": "360", **base}

    db.penunjang_medis.insert_many([
        penunjang("2", "2026-10-08", laboratorium={"nama_laboratorium": "Lab Patologi", "jenis_pemeriksaan": "Hematologi",
                                                  "hasil_laboratorium": "Normal", "id_pegawai": "360"}),
        penunjang("6", "2026-10-08", radiologi={"nama_ruang_radiologi": "Radiologi 1", "id_pegawai": "360"}),
        penunjang("8", "2026-10-09", farmasi={"laporan_transaksi_obat": "ok", "id_pegawai": "360"}),
    ])
    db.diagnosis.insert_many([{"id_diagnosis": "1", "kode_diagnosis": "A09", "id_pelayanan_medis": "1"}])
    db.entri_pendaftaran.insert_many([{"id_entri": "10", "no_registrasi": "1"}])
    db.entri_pelayanan.insert_many([{"id_entri": "11", "id_pelayanan_medis": "1"}])
    db.entri_rme.insert_many([
        {"id_entri": "10", "isi_entri": "Pasien datang", "waktu_entri": "2026-10-05 07:00:00"},
        {"id_entri": "11", "isi_entri": "Diberi obat", "waktu_entri": "2026-10-05 08:10:00"},
    ])
    db.pembayaran.insert_many([
        {"no_billing": "1", "no_registrasi": "1", "tanggal_pembayaran": "2026-10-10", "metode_pembayaran": "Non-Tunai",
         "status_pembayaran": "Berhasil", "jumlah_pembayaran": "1250000.00", "id_pegawai": "70"},
        {"no_billing": "2", "no_registrasi": "3", "tanggal_pembayaran": "2026-10-12", "metode_pembayaran": "Tunai",
         "status_pembayaran": "Berhasil", "jumlah_pembayaran": "100000.00", "id_pegawai": "70"},
        {"no_billing": "3", "no_registrasi": "2", "tanggal_pembayaran": "2026-10-15", "metode_pembayaran": "Tunai",
         "status_pembayaran": "Gagal", "jumlah_pembayaran": "150000.00", "id_pegawai": "70"},
        {"no_billing": "4", "no_registrasi": "1", "tanggal_pembayaran": "2026-09-30", "metode_pembayaran": "Tunai",
         "status_pembayaran": "Berhasil", "jumlah_pembayaran": "10.00", "id_pegawai": "70"},
    ])
    db.kelas_ruangan.insert_many([{"id_kelas": "1", "nama_kelas": "VIP"}, {"id_kelas": "2", "nama_kelas": "Kelas 3"}])
    db.ruangan.insert_many([
        {"id_ruangan": "1", "nama_ruangan": "Kamar 001", "kapasitas_ruangan": "2", "status_ruangan": "Tersedia",
         "id_unit": "22", "rawat_inap": {"id_kelas": "1"}},
        {"id_ruangan": "2", "nama_ruangan": "Kamar 002", "kapasitas_ruangan": "1", "status_ruangan": "Tersedia",
         "id_unit": "22", "rawat_inap": {"id_kelas": "2"}},
        {"id_ruangan": "3", "nama_ruangan": "Kamar 003", "kapasitas_ruangan": "1", "status_ruangan": "Penuh",
         "id_unit": "22", "rawat_inap": {"id_kelas": "2"}},
        {"id_ruangan": "4", "nama_ruangan": "Ruang Periksa", "kapasitas_ruangan": "1", "status_ruangan": "Tersedia",
         "id_unit": "11", "rawat_inap": None},
    ])
    db.penempatan_ruangan.insert_many([
        {"no_registrasi": "1", "waktu_masuk": "2026-10-05 12:00:00", "id_ruangan": "1", "waktu_keluar": None},
        {"no_registrasi": "3", "waktu_masuk": "2026-10-01 12:00:00", "id_ruangan": "1", "waktu_keluar": "2026-10-03 08:00:00"},
        {"no_registrasi": "2", "waktu_masuk": "2026-10-06 12:00:00", "id_ruangan": "2", "waktu_keluar": None},
    ])


@pytest.fixture
def db():
    database = mongomock.MongoClient().simrs
    seed(database)
    return database


@pytest.fixture
def redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(cache, "redis", fake)
    return fake


@pytest.fixture
def client(db, redis):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()
