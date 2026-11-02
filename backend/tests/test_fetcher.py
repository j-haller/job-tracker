import sqlite3
import threading
from pathlib import Path

import pytest

from app import db, sources
from app.fetcher import MAX_DETAIL_ATTEMPTS, FetchManager, parse_settings, run_fetch
from app.sources.base import ListingData, SourceConfigError, SourceUnavailable

COMMON = {
    "enabled": True,
    "interval_minutes": 60,
    "fetch_on_startup": False,
    "request_delay_seconds": 0,
    "timeout_seconds": 5,
}


def listing(external_id: str, title: str = "Dev") -> ListingData:
    return ListingData(external_id, title, "ACME", "Bern", "100%", None, None, None, {"id": external_id})


class FakeSource:
    def __init__(self, key: str = "fake", items: list[ListingData] | None = None) -> None:
        self.key = key
        self.items = items or []
        self.search_error: Exception | None = None
        self.detail_errors: dict[str, Exception] = {}
        self.detail_calls: list[str] = []

    def search(self) -> list[ListingData]:
        if self.search_error:
            raise self.search_error
        return list(self.items)

    def fetch_detail(self, item: ListingData) -> ListingData:
        self.detail_calls.append(item.external_id)
        if item.external_id in self.detail_errors:
            raise self.detail_errors[item.external_id]
        item.url = f"https://public.test/{item.external_id}"
        item.description_text = f"Text {item.external_id}"
        return ListingData(**{**item.__dict__, "raw": {"detail": item.external_id}})


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "jobs.db"
    db.init_db(path)
    return path


@pytest.fixture
def conn(db_path: Path):
    connection = db.open_connection(db_path)
    yield connection
    connection.close()


def rows(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    return {row["id"]: row for row in conn.execute("SELECT * FROM listings")}


def last_run(conn: sqlite3.Connection, key: str = "fake") -> dict:
    return db.last_run(conn, key)


def test_first_run_fills_db(db_path, conn):
    assert run_fetch(db_path, FakeSource(items=[listing("1"), listing("2")]), 0) == "ok"
    stored = rows(conn)
    assert set(stored) == {"fake:1", "fake:2"}
    row = stored["fake:1"]
    assert row["source"] == "fake" and row["external_id"] == "1" and row["status"] == "new"
    assert row["description_text"] == "Text 1"
    assert row["url"] == "https://public.test/1"
    assert '"detail"' in row["detail_json"] and '"id"' in row["search_json"]
    assert row["detail_fetched_at"] and row["detail_error"] is None
    run = last_run(conn)
    assert (run["status"], run["found"], run["new"], run["details_ok"], run["details_failed"]) == ("ok", 2, 2, 2, 0)
    assert run["finished_at"]


def test_second_run_adds_no_duplicates_and_skips_details(db_path, conn):
    source = FakeSource(items=[listing("1"), listing("2")])
    run_fetch(db_path, source, 0)
    source.items = [listing("1", "New title"), listing("2")]
    source.detail_calls.clear()
    run_fetch(db_path, source, 0)
    stored = rows(conn)
    assert len(stored) == 2
    assert stored["fake:1"]["title"] == "New title"
    assert stored["fake:1"]["url"] == "https://public.test/1"
    assert stored["fake:1"]["description_text"] == "Text 1"
    assert source.detail_calls == []
    assert last_run(conn)["new"] == 0


def test_status_note_and_ratings_survive_refetch(db_path, conn):
    source = FakeSource(items=[listing("1")])
    run_fetch(db_path, source, 0)
    with conn:
        conn.execute("UPDATE listings SET status = 'applied', note = 'Called them', status_updated_at = 'x'")
        conn.execute(
            "INSERT INTO ratings (listing_id, backend, model, rating, response_json, profile_hash, created_at) "
            "VALUES ('fake:1', 'claude', 'm', 50, '{}', 'h', 'x')"
        )
    first_seen = rows(conn)["fake:1"]["first_seen_at"]
    source.items = [listing("1")]
    run_fetch(db_path, source, 0)
    row = rows(conn)["fake:1"]
    assert (row["status"], row["note"], row["status_updated_at"]) == ("applied", "Called them", "x")
    assert row["first_seen_at"] == first_seen
    assert conn.execute("SELECT COUNT(*) FROM ratings").fetchone()[0] == 1


def test_failed_search_changes_nothing(db_path, conn):
    source = FakeSource(items=[listing("1")])
    run_fetch(db_path, source, 0)
    before = dict(rows(conn)["fake:1"])
    source.search_error = RuntimeError("boom")
    assert run_fetch(db_path, source, 0) == "failed"
    assert dict(rows(conn)["fake:1"]) == before
    run = last_run(conn)
    assert run["status"] == "failed" and run["error"] == "boom"


def test_missing_listing_goes_inactive_and_comes_back(db_path, conn, monkeypatch):
    times = iter(f"2026-01-01T00:00:{second:02d}+00:00" for second in range(60))
    monkeypatch.setattr(db, "utc_now", lambda: next(times))
    source = FakeSource(items=[listing("1"), listing("2")])
    run_fetch(db_path, source, 0)
    source.items = [listing("1")]
    run_fetch(db_path, source, 0)
    assert rows(conn)["fake:1"]["is_active"] == 1
    assert rows(conn)["fake:2"]["is_active"] == 0
    source.items = [listing("1"), listing("2")]
    run_fetch(db_path, source, 0)
    assert rows(conn)["fake:2"]["is_active"] == 1


def test_inactive_only_within_own_source(db_path, conn, monkeypatch):
    times = iter(f"2026-01-01T00:00:{second:02d}+00:00" for second in range(60))
    monkeypatch.setattr(db, "utc_now", lambda: next(times))
    run_fetch(db_path, FakeSource("other", [listing("9")]), 0)
    run_fetch(db_path, FakeSource("fake", [listing("1")]), 0)
    assert rows(conn)["other:9"]["is_active"] == 1


def test_same_external_id_in_two_sources_stays_separate(db_path, conn):
    run_fetch(db_path, FakeSource("a", [listing("1")]), 0)
    run_fetch(db_path, FakeSource("b", [listing("1")]), 0)
    assert set(rows(conn)) == {"a:1", "b:1"}


def test_detail_failure_is_partial_and_retried_at_most_three_times(db_path, conn):
    source = FakeSource(items=[listing("1"), listing("2")])
    source.detail_errors["1"] = RuntimeError("gone")
    assert run_fetch(db_path, source, 0) == "partial"
    row = rows(conn)["fake:1"]
    assert row["detail_error"] == "gone" and row["detail_attempts"] == 1
    assert rows(conn)["fake:2"]["description_text"] == "Text 2"
    run = last_run(conn)
    assert (run["details_ok"], run["details_failed"]) == (1, 1)

    for _ in range(MAX_DETAIL_ATTEMPTS + 2):
        source.items = [listing("1"), listing("2")]
        run_fetch(db_path, source, 0)
    assert source.detail_calls.count("1") == 4  # first attempt + 3 retries
    assert source.detail_calls.count("2") == 1
    assert rows(conn)["fake:1"]["detail_attempts"] == 4
    assert last_run(conn)["status"] == "ok"


def test_retry_success_clears_error(db_path, conn):
    source = FakeSource(items=[listing("1")])
    source.detail_errors["1"] = RuntimeError("gone")
    run_fetch(db_path, source, 0)
    source.detail_errors.clear()
    source.items = [listing("1")]
    assert run_fetch(db_path, source, 0) == "ok"
    row = rows(conn)["fake:1"]
    assert row["detail_error"] is None and row["description_text"] == "Text 1"


def test_unavailable_site_stops_details_without_counting_attempt(db_path, conn):
    source = FakeSource(items=[listing("1"), listing("2")])
    source.detail_errors["1"] = SourceUnavailable("HTTP 429")
    assert run_fetch(db_path, source, 0) == "partial"
    assert source.detail_calls == ["1"]
    assert rows(conn)["fake:1"]["detail_attempts"] == 0
    assert rows(conn)["fake:1"]["detail_error"] == "HTTP 429"
    assert rows(conn)["fake:2"]["detail_error"] is None


def test_delay_between_detail_calls_only(db_path, monkeypatch):
    from app import fetcher

    delays: list[float] = []
    monkeypatch.setattr(fetcher.time, "sleep", delays.append)
    run_fetch(db_path, FakeSource(items=[listing("1"), listing("2"), listing("3")]), 1.5)
    assert delays == [1.5, 1.5]


def test_source_with_own_description_needs_no_detail(db_path, conn):
    item = listing("1")
    item.description_text = "From search"
    source = FakeSource(items=[item])
    run_fetch(db_path, source, 0)
    assert source.detail_calls == []
    assert rows(conn)["fake:1"]["description_text"] == "From search"


def test_failing_source_does_not_affect_others(db_path, conn, monkeypatch):
    good = FakeSource("good", [listing("1")])
    bad = FakeSource("bad")
    bad.search_error = RuntimeError("down")
    monkeypatch.setitem(sources.ADAPTERS, "good", lambda settings: good)
    monkeypatch.setitem(sources.ADAPTERS, "bad", lambda settings: bad)
    manager = FetchManager(
        db_path,
        {"bad": {**COMMON, "adapter": "bad"}, "good": {**COMMON, "adapter": "good"}},
    )
    manager.run_scheduled("bad")
    manager.run_scheduled("good")
    assert last_run(conn, "bad")["status"] == "failed"
    assert last_run(conn, "good")["status"] == "ok"
    assert set(rows(conn)) == {"good:1"}


def test_invalid_config_block_leaves_other_sources_running(db_path, conn, monkeypatch):
    good = FakeSource("good", [listing("1")])
    monkeypatch.setitem(sources.ADAPTERS, "good", lambda settings: good)
    manager = FetchManager(
        db_path,
        {
            "good": {**COMMON, "adapter": "good"},
            "broken": {**COMMON, "adapter": "nope"},
            "partial": {"enabled": True},
            "not_a_table": 5,
        },
    )
    assert manager.entries["good"].runnable
    assert "Unknown adapter" in manager.entries["broken"].error
    assert "Missing settings" in manager.entries["partial"].error
    assert "table" in manager.entries["not_a_table"].error
    assert not any(manager.entries[key].runnable for key in ("broken", "partial", "not_a_table"))
    manager.run_scheduled("good")
    assert last_run(conn, "good")["status"] == "ok"


def test_invalid_jobsch_settings_are_reported_not_raised(db_path):
    manager = FetchManager(db_path, {"jobsch": {**COMMON, "adapter": "jobsch", "search_url": "nope"}})
    assert "search_url" in manager.entries["jobsch"].error


def test_disabled_source_is_not_runnable(db_path, monkeypatch):
    monkeypatch.setitem(sources.ADAPTERS, "good", lambda settings: FakeSource("good"))
    manager = FetchManager(db_path, {"good": {**COMMON, "enabled": False, "adapter": "good"}})
    assert not manager.entries["good"].runnable


@pytest.mark.parametrize(
    "changes",
    [
        {"interval_minutes": 0},
        {"interval_minutes": True},
        {"enabled": "yes"},
        {"request_delay_seconds": -1},
        {"timeout_seconds": 0},
        {"adapter": 1},
    ],
)
def test_invalid_common_settings(changes):
    with pytest.raises(SourceConfigError):
        parse_settings("fake", {**COMMON, "adapter": "fake", **changes})


def test_options_exclude_common_keys():
    settings = parse_settings("fake", {**COMMON, "adapter": "fake", "search_url": "u"})
    assert settings.options == {"search_url": "u"}


def test_running_source_is_skipped(db_path, conn, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    class SlowSource(FakeSource):
        def search(self):
            entered.set()
            release.wait(5)
            return []

    monkeypatch.setitem(sources.ADAPTERS, "slow", lambda settings: SlowSource("slow"))
    manager = FetchManager(db_path, {"slow": {**COMMON, "adapter": "slow"}})
    assert manager.start_in_background("slow") is True
    assert entered.wait(5)
    assert manager.start_in_background("slow") is False
    manager.run_scheduled("slow")
    assert conn.execute("SELECT COUNT(*) FROM fetch_runs").fetchone()[0] == 1
    release.set()
    with manager.entries["slow"].lock:
        pass
    assert last_run(conn, "slow")["status"] == "ok"


def test_startup_closes_interrupted_runs(db_path, conn):
    db.start_run(conn, "fake")
    db.init_db(db_path)
    run = last_run(conn)
    assert run["status"] == "failed" and run["error"] == "Interrupted by restart"


def test_migrations_tracked_in_user_version(db_path, conn):
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)
    db.init_db(db_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
