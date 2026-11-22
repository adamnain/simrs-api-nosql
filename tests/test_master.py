import pytest

PATHS = ["kelas-ruangan", "tarif-kelas", "unit-layanan", "penjamin", "layanan", "obat", "ruangan", "jadwal-dokter"]


@pytest.mark.parametrize("path", PATHS)
def test_first_call_reads_mongodb_then_redis(client, path):
    first = client.get(f"/api/master/{path}")
    second = client.get(f"/api/master/{path}")

    assert first.status_code == second.status_code == 200
    assert first.json()["metadata"]["source"] == "mongodb"
    assert second.json()["metadata"]["source"] == "redis"
    assert first.json()["data"] == second.json()["data"]
    assert second.json()["metadata"]["total"] == len(second.json()["data"])


@pytest.mark.parametrize("path", ["penyediaan-layanan", "pegawai", "kelas-ruangan/1", "layanan/63"])
def test_routes_not_offered(client, path):
    assert client.get(f"/api/master/{path}").status_code == 404


def test_metadata_names_collection(client):
    body = client.get("/api/master/unit-layanan").json()
    assert body["metadata"] == {"source": "mongodb", "collection": "unit_layanan", "total": 3}
    assert [r["id_unit"] for r in body["data"]] == ["11", "22", "32"]


def test_shares_cache_with_get_master_for_untouched_collections(client, redis):
    # The S04 endpoint fills simrs:master:layanan via get_master; the master route must reuse it.
    client.get("/api/pendaftaran/1/layanan")
    assert "simrs:master:layanan" in redis.store
    assert client.get("/api/master/layanan").json()["metadata"]["source"] == "redis"


def test_ruangan_leaves_out_live_status(client, redis):
    rows = client.get("/api/master/ruangan").json()["data"]
    assert rows and all("status_ruangan" not in r for r in rows)
    assert "simrs:master:ruangan" in redis.store


def test_works_without_redis(client, monkeypatch):
    from app import cache
    monkeypatch.setattr(cache, "redis", None)
    for _ in range(2):
        assert client.get("/api/master/obat").json()["metadata"]["source"] == "mongodb"

