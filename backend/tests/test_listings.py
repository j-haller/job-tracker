import hashlib
from pathlib import Path

import pytest

from app import db
from app.fetcher import run_fetch
from tests.fakes import FakeSource, listing


@pytest.fixture
def app(make_app):
    return make_app()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "jobs.db"


@pytest.fixture
def filled(app, db_path: Path) -> FakeSource:
    source = FakeSource(items=[listing("1"), listing("2")])
    run_fetch(db_path, source, 0)
    return source


def add_rating(db_path: Path, listing_id: str, rating: int, created_at: str, profile_hash: str = "old", **fields) -> None:
    values = {
        "listing_id": listing_id,
        "backend": "claude",
        "model": "claude-haiku-5-5",
        "rating": rating,
        "response_json": "{}",
        "profile_hash": profile_hash,
        "created_at": created_at,
        **fields,
    }
    marks = ", ".join("?" for _ in values)
    with db.connection(db_path) as conn, conn:
        conn.execute(f"INSERT INTO ratings ({', '.join(values)}) VALUES ({marks})", tuple(values.values()))


def test_list_is_empty_without_listings(client):
    res = client.get("/api/listings")
    assert res.status_code == 200 and res.get_json() == []


def test_list_leaves_out_long_texts_and_raw_data(client, filled):
    rows = client.get("/api/listings").get_json()
    assert {row["id"] for row in rows} == {"fake:1", "fake:2"}
    row = next(r for r in rows if r["id"] == "fake:1")
    for hidden in ("description_text", "search_json", "detail_json", "rating_profile_hash", "duplicate_of"):
        assert hidden not in row
    assert row["title"] == "Dev" and row["url"] == "https://public.test/1"
    assert row["is_active"] is True and row["status"] == "new"
    assert row["rating"] is None and row["is_stale"] is False and row["also_on"] == []


def test_list_shows_newest_rating(client, filled, db_path):
    add_rating(db_path, "fake:1", 40, "2026-01-01T00:00:00+00:00")
    add_rating(db_path, "fake:1", 70, "2026-02-01T00:00:00+00:00", summary="Good", missing_required=2)
    row = next(r for r in client.get("/api/listings").get_json() if r["id"] == "fake:1")
    assert (row["rating"], row["summary"], row["missing_required"]) == (70, "Good", 2)
    assert row["rated_at"] == "2026-02-01T00:00:00+00:00"


def test_rating_is_stale_when_profile_changed(client, filled, db_path, tmp_path: Path):
    (tmp_path / "profile.md").write_text("Target roles: DBA", encoding="utf-8")
    current = hashlib.sha256(b"Target roles: DBA").hexdigest()
    add_rating(db_path, "fake:1", 40, "2026-01-01T00:00:00+00:00", profile_hash=current)
    add_rating(db_path, "fake:2", 40, "2026-01-01T00:00:00+00:00", profile_hash="old")
    rows = {r["id"]: r for r in client.get("/api/listings").get_json()}
    assert rows["fake:1"]["is_stale"] is False
    assert rows["fake:2"]["is_stale"] is True


def test_detail_has_description_requirements_and_history(client, filled, db_path):
    add_rating(db_path, "fake:1", 40, "2026-01-01T00:00:00+00:00")
    add_rating(
        db_path,
        "fake:1",
        70,
        "2026-02-01T00:00:00+00:00",
        requirements_json='[{"text": "SQL", "match": "yes"}]',
        dealbreakers_json='["No Avaloq"]',
    )
    res = client.get("/api/listings/fake:1")
    assert res.status_code == 200
    body = res.get_json()
    assert body["description_text"] == "Text 1"
    assert body["rating"] == 70
    assert body["requirements"] == [{"text": "SQL", "match": "yes"}]
    assert body["dealbreakers"] == ["No Avaloq"]
    assert [item["rating"] for item in body["rating_history"]] == [70, 40]
    assert "search_json" not in body and "detail_json" not in body
    assert "response_json" not in body["rating_history"][0]


def test_detail_without_rating(client, filled):
    body = client.get("/api/listings/fake:1").get_json()
    assert body["requirements"] == [] and body["dealbreakers"] == [] and body["rating_history"] == []


def test_detail_unknown_id(client):
    res = client.get("/api/listings/fake:999")
    assert res.status_code == 404 and "error" in res.get_json()


@pytest.mark.parametrize("path", ["fake%3Aa%2Fb", "fake:a%2Fb"])
def test_url_encoded_id_with_slash(client, app, db_path, path):
    run_fetch(db_path, FakeSource(items=[listing("a/b")]), 0)
    assert client.get(f"/api/listings/{path}").get_json()["id"] == "fake:a/b"
    res = client.post(f"/api/listings/{path}/status", json={"status": "applied"})
    assert res.status_code == 200 and res.get_json()["status"] == "applied"


def test_status_update(client, filled):
    res = client.post("/api/listings/fake:1/status", json={"status": "applied", "note": "Called them"})
    assert res.status_code == 200
    body = res.get_json()
    assert body["status"] == "applied" and body["note"] == "Called them"
    assert body["status_updated_at"]
    assert body["description_text"] == "Text 1"
    assert client.get("/api/listings/fake:2").get_json()["status"] == "new"


def test_status_and_note_survive_next_fetch(client, filled, db_path):
    client.post("/api/listings/fake:1/status", json={"status": "interview", "note": "Monday"})
    filled.items = [listing("1", "Changed title"), listing("2")]
    run_fetch(db_path, filled, 0)
    body = client.get("/api/listings/fake:1").get_json()
    assert (body["status"], body["note"]) == ("interview", "Monday")
    assert body["title"] == "Changed title"


def test_missing_note_keeps_stored_note(client, filled):
    client.post("/api/listings/fake:1/status", json={"status": "applied", "note": "Keep me"})
    body = client.post("/api/listings/fake:1/status", json={"status": "interview"}).get_json()
    assert body["note"] == "Keep me"


def test_null_note_clears_stored_note(client, filled):
    client.post("/api/listings/fake:1/status", json={"status": "applied", "note": "Old"})
    body = client.post("/api/listings/fake:1/status", json={"status": "applied", "note": None}).get_json()
    assert body["note"] is None


def test_status_updated_at_only_moves_on_real_change(client, filled, monkeypatch):
    times = iter(["2026-01-01T00:00:00+00:00", "2026-02-01T00:00:00+00:00", "2026-03-01T00:00:00+00:00"])
    monkeypatch.setattr(db, "utc_now", lambda: next(times))
    first = client.post("/api/listings/fake:1/status", json={"status": "applied"}).get_json()
    same = client.post("/api/listings/fake:1/status", json={"status": "applied", "note": "x"}).get_json()
    changed = client.post("/api/listings/fake:1/status", json={"status": "offer"}).get_json()
    assert first["status_updated_at"] == same["status_updated_at"] == "2026-01-01T00:00:00+00:00"
    assert changed["status_updated_at"] == "2026-03-01T00:00:00+00:00"


@pytest.mark.parametrize(
    "body",
    [
        {"status": "hired"},
        {"status": None},
        {"status": ["applied"]},
        {"note": "only a note"},
        {"status": "applied", "note": 5},
        ["applied"],
    ],
)
def test_invalid_status_body(client, filled, body):
    res = client.post("/api/listings/fake:1/status", json=body)
    assert res.status_code == 400 and "error" in res.get_json()
    stored = client.get("/api/listings/fake:1").get_json()
    assert stored["status"] == "new" and stored["note"] is None


def test_status_body_not_json(client, filled):
    res = client.post("/api/listings/fake:1/status", data="status=applied")
    assert res.status_code == 400


def test_status_unknown_listing(client):
    res = client.post("/api/listings/fake:999/status", json={"status": "applied"})
    assert res.status_code == 404 and "error" in res.get_json()


def test_duplicate_is_attached_not_listed(client, filled, db_path):
    run_fetch(db_path, FakeSource("other", [listing("9")]), 0)
    with db.connection(db_path) as conn, conn:
        conn.execute("UPDATE listings SET duplicate_of = 'fake:1', url = 'https://other.test/9' WHERE id = 'other:9'")
    rows = {r["id"]: r for r in client.get("/api/listings").get_json()}
    assert "other:9" not in rows
    expected = [{"source": "other", "url": "https://other.test/9"}]
    assert rows["fake:1"]["also_on"] == expected
    assert client.get("/api/listings/fake:1").get_json()["also_on"] == expected
    assert client.get("/api/listings/other:9").status_code == 404
    assert client.post("/api/listings/other:9/status", json={"status": "applied"}).status_code == 404
