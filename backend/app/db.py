"""SQLite connection, schema migrations and listing queries."""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from .sources.base import ListingData

SCHEMA_FILE = Path(__file__).with_name("schema.sql")

# Numbered migrations, tracked in PRAGMA user_version. Append only.
MIGRATIONS: list[str] = [SCHEMA_FILE.read_text(encoding="utf-8")]


@dataclass
class RunCounts:
    found: int = 0
    new: int = 0
    details_ok: int = 0
    details_failed: int = 0


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def open_connection(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def connection(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = open_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()


def init_db(db_path: Path) -> None:
    """Apply pending migrations and close runs a previous process left open."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connection(db_path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > len(MIGRATIONS):
            raise RuntimeError(f"Database version {version} is newer than this app")
        for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
            conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {number};\nCOMMIT;")
        with conn:
            conn.execute(
                "UPDATE fetch_runs SET status = 'failed', finished_at = ?, "
                "error = 'Interrupted by restart' WHERE status = 'running'",
                (utc_now(),),
            )


def start_run(conn: sqlite3.Connection, source: str) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO fetch_runs (source, started_at, status) VALUES (?, ?, 'running')",
            (source, utc_now()),
        )
    return int(cur.lastrowid)


def finish_run(
    conn: sqlite3.Connection, run_id: int, status: str, counts: RunCounts, error: str | None = None
) -> None:
    with conn:
        conn.execute(
            "UPDATE fetch_runs SET finished_at = ?, status = ?, found = ?, new = ?, "
            "details_ok = ?, details_failed = ?, error = ? WHERE id = ?",
            (
                utc_now(),
                status,
                counts.found,
                counts.new,
                counts.details_ok,
                counts.details_failed,
                error,
                run_id,
            ),
        )


# status, note, ratings, duplicate_of and first_seen_at are deliberately not updated.
# The search result may lack url and description, so it never blanks stored ones.
_UPSERT = """
INSERT INTO listings (
  id, source, external_id, title, company, location, workload, published_at,
  url, description_text, search_json, first_seen_at, last_seen_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (id) DO UPDATE SET
  title = excluded.title,
  company = excluded.company,
  location = excluded.location,
  workload = excluded.workload,
  published_at = excluded.published_at,
  url = COALESCE(excluded.url, listings.url),
  description_text = COALESCE(excluded.description_text, listings.description_text),
  search_json = excluded.search_json,
  last_seen_at = excluded.last_seen_at,
  is_active = 1
"""


def listing_id(source: str, external_id: str) -> str:
    return f"{source}:{external_id}"


def store_search_result(conn: sqlite3.Connection, source: str, items: list[ListingData]) -> int:
    """Upsert a full result set and deactivate this source's missing listings.

    One transaction, so a failure leaves the listings unchanged. Returns the new count.
    """
    now = utc_now()
    with conn:
        known = {r["id"] for r in conn.execute("SELECT id FROM listings WHERE source = ?", (source,))}
        ids = {listing_id(source, item.external_id) for item in items}
        conn.executemany(_UPSERT, [_upsert_row(source, item, now) for item in items])
        conn.execute(
            "UPDATE listings SET is_active = 0 WHERE source = ? AND last_seen_at <> ?",
            (source, now),
        )
    return len(ids - known)


def _upsert_row(source: str, item: ListingData, now: str) -> tuple:
    return (
        listing_id(source, item.external_id),
        source,
        item.external_id,
        item.title,
        item.company,
        item.location,
        item.workload,
        item.published_at,
        item.url,
        item.description_text,
        json.dumps(item.raw, ensure_ascii=False),
        now,
        now,
    )


def external_ids_needing_detail(conn: sqlite3.Connection, source: str, max_attempts: int) -> set[str]:
    rows = conn.execute(
        "SELECT external_id FROM listings WHERE source = ? AND is_active = 1 "
        "AND description_text IS NULL AND detail_attempts < ?",
        (source, max_attempts),
    )
    return {row["external_id"] for row in rows}


def store_detail(conn: sqlite3.Connection, source: str, item: ListingData) -> None:
    with conn:
        conn.execute(
            "UPDATE listings SET url = COALESCE(?, url), description_text = ?, detail_json = ?, "
            "detail_fetched_at = ?, detail_error = NULL WHERE id = ?",
            (
                item.url,
                item.description_text,
                json.dumps(item.raw, ensure_ascii=False),
                utc_now(),
                listing_id(source, item.external_id),
            ),
        )


def store_detail_error(
    conn: sqlite3.Connection, source: str, external_id: str, error: str, count_attempt: bool
) -> None:
    with conn:
        conn.execute(
            "UPDATE listings SET detail_error = ?, detail_attempts = detail_attempts + ? WHERE id = ?",
            (error, 1 if count_attempt else 0, listing_id(source, external_id)),
        )


def last_run(conn: sqlite3.Connection, source: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM fetch_runs WHERE source = ? ORDER BY id DESC LIMIT 1", (source,)
    ).fetchone()
    return dict(row) if row else None


def listing_counts(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS total, COALESCE(SUM(is_active), 0) AS active FROM listings"
    ).fetchone()
    return dict(row)
