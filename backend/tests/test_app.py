import hashlib
from pathlib import Path

from app import sources
from tests.fakes import slow_source_factory

SOURCES_TOML = """
[fake]
enabled = true
adapter = "fake"
interval_minutes = 60
fetch_on_startup = false
request_delay_seconds = 0
timeout_seconds = 5

[broken]
enabled = true
adapter = "nope"
interval_minutes = 60
fetch_on_startup = false
request_delay_seconds = 0
timeout_seconds = 5
"""


def test_status_without_profile(make_app):
    res = make_app().test_client().get("/api/status")
    assert res.status_code == 200
    body = res.get_json()
    assert body["profile"] == {"present": False, "hash": None, "length": 0}
    assert body["rating_backend"] == "claude"
    assert body["sources"] == []
    assert body["sources_config_error"] is None
    assert body["listings"] == {"total": 0, "active": 0}


def test_status_with_profile(make_app, tmp_path: Path):
    (tmp_path / "profile.md").write_text("Target roles: DBA", encoding="utf-8")
    body = make_app().test_client().get("/api/status").get_json()
    assert body["profile"]["present"] is True
    assert body["profile"]["hash"] == hashlib.sha256(b"Target roles: DBA").hexdigest()


def test_broken_sources_file_is_reported(make_app, tmp_path: Path):
    (tmp_path / "sources.toml").write_text("not [ toml", encoding="utf-8")
    body = make_app().test_client().get("/api/status").get_json()
    assert "Cannot read sources config" in body["sources_config_error"]
    assert body["sources"] == []


def test_status_per_source(make_app, tmp_path: Path, monkeypatch):
    (tmp_path / "sources.toml").write_text(SOURCES_TOML, encoding="utf-8")
    factory, _ = slow_source_factory()
    monkeypatch.setitem(sources.ADAPTERS, "fake", factory)
    body = make_app().test_client().get("/api/status").get_json()
    by_key = {source["key"]: source for source in body["sources"]}
    assert by_key["fake"]["enabled"] is True and by_key["fake"]["config_error"] is None
    assert by_key["fake"]["last_run"] is None and by_key["fake"]["next_run_at"] is None
    assert by_key["broken"]["enabled"] is False
    assert "Unknown adapter" in by_key["broken"]["config_error"]


def test_fetch_endpoint(make_app, tmp_path: Path, monkeypatch):
    (tmp_path / "sources.toml").write_text(SOURCES_TOML, encoding="utf-8")
    factory, control = slow_source_factory()
    monkeypatch.setitem(sources.ADAPTERS, "fake", factory)
    app = make_app()
    client = app.test_client()

    assert client.post("/api/fetch?source=missing").status_code == 404
    assert client.post("/api/fetch?source=broken").status_code == 400

    res = client.post("/api/fetch?source=fake")
    assert res.status_code == 202 and res.get_json() == {"started": ["fake"]}
    assert control.entered.wait(5)
    assert client.get("/api/status").get_json()["sources"][0]["running"] is True
    assert client.post("/api/fetch?source=fake").status_code == 409
    assert client.post("/api/fetch").status_code == 409

    control.release.set()
    with app.config["FETCH_MANAGER"].entries["fake"].lock:
        pass
    last_run = client.get("/api/status").get_json()["sources"][0]["last_run"]
    assert last_run["status"] == "ok"
    assert client.post("/api/fetch").get_json() == {"started": ["fake"]}
    with app.config["FETCH_MANAGER"].entries["fake"].lock:
        pass


def test_unknown_api_path_returns_json_404(make_app):
    res = make_app().test_client().get("/api/nope")
    assert res.status_code == 404
    assert "error" in res.get_json()


def test_frontend_fallback_to_index(make_app, tmp_path: Path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<p>hello</p>")
    (static / "app.js").write_text("console.log(1)")
    client = make_app(static).test_client()
    assert b"hello" in client.get("/").data
    assert b"hello" in client.get("/some/view").data
    assert b"console" in client.get("/app.js").data
