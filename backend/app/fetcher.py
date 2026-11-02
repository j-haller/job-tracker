"""Generic fetch run per source. No source-specific code here."""

import logging
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import db
from .db import RunCounts
from .sources import build_source
from .sources.base import ListingData, Source, SourceConfigError, SourceSettings, SourceUnavailable

logger = logging.getLogger(__name__)

MAX_DETAIL_ATTEMPTS = 4  # the first attempt plus 3 retries on later runs
MAX_ERROR_LENGTH = 500
_KEY_PATTERN = re.compile(r"[a-z0-9_]+")
_COMMON_KEYS = (
    "enabled",
    "adapter",
    "interval_minutes",
    "fetch_on_startup",
    "request_delay_seconds",
    "timeout_seconds",
)


def parse_settings(key: str, raw: object) -> SourceSettings:
    """Validate the common keys; everything else goes to the adapter as options."""
    if not _KEY_PATTERN.fullmatch(key):
        raise SourceConfigError("Source key may only contain a-z, 0-9 and _")
    if not isinstance(raw, dict):
        raise SourceConfigError("Source settings must be a table")
    missing = [name for name in _COMMON_KEYS if name not in raw]
    if missing:
        raise SourceConfigError(f"Missing settings: {', '.join(missing)}")
    if not isinstance(raw["enabled"], bool) or not isinstance(raw["fetch_on_startup"], bool):
        raise SourceConfigError("enabled and fetch_on_startup must be true or false")
    if not isinstance(raw["adapter"], str):
        raise SourceConfigError("adapter must be a string")
    interval = raw["interval_minutes"]
    if not isinstance(interval, int) or isinstance(interval, bool) or interval < 1:
        raise SourceConfigError("interval_minutes must be a positive integer")
    if not _is_number(raw["request_delay_seconds"]) or raw["request_delay_seconds"] < 0:
        raise SourceConfigError("request_delay_seconds must be zero or more")
    if not _is_number(raw["timeout_seconds"]) or raw["timeout_seconds"] <= 0:
        raise SourceConfigError("timeout_seconds must be greater than zero")
    options = {name: value for name, value in raw.items() if name not in _COMMON_KEYS}
    return SourceSettings(
        key=key,
        enabled=raw["enabled"],
        adapter=raw["adapter"],
        interval_minutes=interval,
        fetch_on_startup=raw["fetch_on_startup"],
        request_delay_seconds=float(raw["request_delay_seconds"]),
        timeout_seconds=float(raw["timeout_seconds"]),
        options=options,
    )


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def run_fetch(db_path: Path, source: Source, request_delay_seconds: float) -> str:
    """Run one fetch for one source and return its final status. Never raises."""
    counts = RunCounts()
    with db.connection(db_path) as conn:
        run_id = db.start_run(conn, source.key)
        try:
            items = source.search()
            counts.found = len(items)
            counts.new = db.store_search_result(conn, source.key, items)
            _fetch_details(conn, source, items, request_delay_seconds, counts)
            status = "partial" if counts.details_failed else "ok"
            db.finish_run(conn, run_id, status, counts)
        except Exception as exc:
            status = "failed"
            logger.exception("Fetch failed for source %s", source.key)
            db.finish_run(conn, run_id, status, counts, _error_text(exc))
    logger.info(
        "Fetch %s: %s, found=%d new=%d details_ok=%d details_failed=%d",
        source.key,
        status,
        counts.found,
        counts.new,
        counts.details_ok,
        counts.details_failed,
    )
    return status


def _fetch_details(
    conn: sqlite3.Connection,
    source: Source,
    items: list[ListingData],
    delay: float,
    counts: RunCounts,
) -> None:
    pending = db.external_ids_needing_detail(conn, source.key, MAX_DETAIL_ATTEMPTS)
    todo = {item.external_id: item for item in items if item.external_id in pending}
    for index, item in enumerate(todo.values()):
        if index:
            time.sleep(delay)
        try:
            db.store_detail(conn, source.key, source.fetch_detail(item))
            counts.details_ok += 1
        except SourceUnavailable as exc:
            # The site's fault, not this listing's: no attempt counted, the rest waits.
            db.store_detail_error(conn, source.key, item.external_id, _error_text(exc), False)
            counts.details_failed += 1
            return
        except Exception as exc:
            db.store_detail_error(conn, source.key, item.external_id, _error_text(exc), True)
            counts.details_failed += 1


def _error_text(exc: Exception) -> str:
    return (str(exc) or type(exc).__name__)[:MAX_ERROR_LENGTH]


@dataclass
class SourceEntry:
    key: str
    settings: SourceSettings | None = None
    source: Source | None = None
    error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def runnable(self) -> bool:
        return self.source is not None and self.settings is not None and self.settings.enabled


def _build_entry(key: str, raw: object) -> SourceEntry:
    entry = SourceEntry(key=key)
    try:
        entry.settings = parse_settings(key, raw)
        entry.source = build_source(entry.settings)
    except Exception as exc:
        entry.error = _error_text(exc)
        logger.error("Source %s disabled: %s", key, entry.error)
    return entry


class FetchManager:
    """Holds all configured sources and makes sure each runs at most once at a time."""

    def __init__(self, db_path: Path, raw_sources: dict) -> None:
        self._db_path = db_path
        self.entries = {key: _build_entry(key, raw) for key, raw in raw_sources.items()}

    def run_scheduled(self, key: str) -> None:
        """Scheduler entry point: skip when this source is still running."""
        entry = self.entries[key]
        if entry.lock.acquire(blocking=False):
            self._run_locked(entry)
        else:
            logger.info("Fetch %s skipped: still running", key)

    def start_in_background(self, key: str) -> bool:
        """Start a manual run. Returns False when this source is already running."""
        entry = self.entries[key]
        if not entry.lock.acquire(blocking=False):
            return False
        thread = threading.Thread(target=self._run_locked, args=(entry,), daemon=True)
        thread.start()
        return True

    def _run_locked(self, entry: SourceEntry) -> None:
        try:
            run_fetch(self._db_path, entry.source, entry.settings.request_delay_seconds)
        finally:
            entry.lock.release()
