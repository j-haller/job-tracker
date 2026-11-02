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

STATUS_VALUES = ("new", "interested", "applied", "interview", "offer", "rejected", "not_interested")

_LISTING_COLUMNS = """
  l.id, l.source, l.external_id, l.title, l.company, l.location, l.workload,
  l.published_at, l.url, l.detail_error, l.first_seen_at, l.last_seen_at,
  l.is_active, l.status, l.status_updated_at, l.note
"""
# The current rating is the newest row in ratings.
_WITH_CURRENT_RATING = """
  r.rating, r.created_at AS rated_at, r.summary, r.missing_required,
  r.profile_hash AS rating_profile_hash
FROM listings l
LEFT JOIN ratings r ON r.id = (
  SELECT id FROM ratings WHERE listing_id = l.id ORDER BY created_at DESC, id DESC LIMIT 1
)
"""


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


def list_listings(conn: sqlite3.Connection, profile_hash: str | None) -> list[dict]:
    """All listings for the table, without long texts or raw data; duplicates are attached."""
    rows = conn.execute(
        f"SELECT {_LISTING_COLUMNS}, {_WITH_CURRENT_RATING} "
        "WHERE l.duplicate_of IS NULL ORDER BY l.first_seen_at DESC, l.id"
    ).fetchall()
    also_on = _duplicates_by_listing(conn)
    return [_listing_dict(row, profile_hash, also_on.get(row["id"], [])) for row in rows]


def get_listing(conn: sqlite3.Connection, listing_key: str, profile_hash: str | None) -> dict | None:
    """One listing with description, current requirements and rating history."""
    row = conn.execute(
        f"SELECT {_LISTING_COLUMNS}, l.description_text, r.requirements_json, r.dealbreakers_json, "
        f"{_WITH_CURRENT_RATING} WHERE l.id = ? AND l.duplicate_of IS NULL",
        (listing_key,),
    ).fetchone()
    if row is None:
        return None
    listing = _listing_dict(row, profile_hash, _duplicates_by_listing(conn).get(listing_key, []))
    listing["description_text"] = row["description_text"]
    listing["requirements"] = json.loads(row["requirements_json"] or "[]")
    listing["dealbreakers"] = json.loads(row["dealbreakers_json"] or "[]")
    listing["rating_history"] = _rating_history(conn, listing_key, profile_hash)
    return listing


def update_status(conn: sqlite3.Connection, listing_key: str, status: str) -> bool:
    """Set the status; status_updated_at only moves when the status really changes."""
    with conn:
        cur = conn.execute(
            "UPDATE listings SET status_updated_at = "
            "CASE WHEN status <> ? THEN ? ELSE status_updated_at END, status = ? "
            "WHERE id = ? AND duplicate_of IS NULL",
            (status, utc_now(), status, listing_key),
        )
    return cur.rowcount > 0


def update_note(conn: sqlite3.Connection, listing_key: str, note: str | None) -> None:
    with conn:
        conn.execute("UPDATE listings SET note = ? WHERE id = ?", (note, listing_key))


def _listing_dict(row: sqlite3.Row, profile_hash: str | None, also_on: list[dict]) -> dict:
    return {
        "id": row["id"],
        "source": row["source"],
        "external_id": row["external_id"],
        "title": row["title"],
        "company": row["company"],
        "location": row["location"],
        "workload": row["workload"],
        "published_at": row["published_at"],
        "url": row["url"],
        "detail_error": row["detail_error"],
        "first_seen_at": row["first_seen_at"],
        "last_seen_at": row["last_seen_at"],
        "is_active": bool(row["is_active"]),
        "status": row["status"],
        "status_updated_at": row["status_updated_at"],
        "note": row["note"],
        "rating": row["rating"],
        "rated_at": row["rated_at"],
        "summary": row["summary"],
        "missing_required": row["missing_required"],
        "is_stale": _is_stale(row["rating_profile_hash"], profile_hash),
        "also_on": also_on,
    }


def _is_stale(rating_hash: str | None, profile_hash: str | None) -> bool:
    return rating_hash is not None and rating_hash != profile_hash


def _duplicates_by_listing(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    rows = conn.execute(
        "SELECT duplicate_of, source, url FROM listings WHERE duplicate_of IS NOT NULL ORDER BY source"
    )
    result: dict[str, list[dict]] = {}
    for row in rows:
        result.setdefault(row["duplicate_of"], []).append({"source": row["source"], "url": row["url"]})
    return result


def _rating_history(conn: sqlite3.Connection, listing_key: str, profile_hash: str | None) -> list[dict]:
    rows = conn.execute(
        "SELECT id, backend, model, rating, summary, missing_required, profile_hash, created_at "
        "FROM ratings WHERE listing_id = ? ORDER BY created_at DESC, id DESC",
        (listing_key,),
    )
    return [
        {
            "id": row["id"],
            "backend": row["backend"],
            "model": row["model"],
            "rating": row["rating"],
            "summary": row["summary"],
            "missing_required": row["missing_required"],
            "created_at": row["created_at"],
            "is_stale": _is_stale(row["profile_hash"], profile_hash),
        }
        for row in rows
    ]
