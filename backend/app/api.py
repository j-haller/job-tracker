"""JSON API under /api."""

import hashlib
from datetime import UTC

from flask import Blueprint, current_app, jsonify, request

from . import db
from .config import Config
from .fetcher import FetchManager, SourceEntry

api = Blueprint("api", __name__, url_prefix="/api")


@api.get("/status")
def status():
    config: Config = current_app.config["APP_CONFIG"]
    manager: FetchManager = current_app.config["FETCH_MANAGER"]
    with db.connection(config.db_path) as conn:
        sources = [_source_status(conn, entry) for entry in manager.entries.values()]
        listings = db.listing_counts(conn)
    return jsonify(
        sources=sources,
        sources_config_error=current_app.config["SOURCES_CONFIG_ERROR"],
        listings=listings,
        profile=_profile_status(config),
        rating_backend=config.rating_backend,
        model=config.claude_model,
    )


@api.get("/listings")
def listings():
    config: Config = current_app.config["APP_CONFIG"]
    with db.connection(config.db_path) as conn:
        return jsonify(db.list_listings(conn, _profile_status(config)["hash"]))


# path converter: IDs come from the source and may contain an encoded slash.
@api.get("/listings/<path:listing_id>")
def listing_detail(listing_id: str):
    config: Config = current_app.config["APP_CONFIG"]
    with db.connection(config.db_path) as conn:
        listing = db.get_listing(conn, listing_id, _profile_status(config)["hash"])
    if listing is None:
        return jsonify(error=f"Unknown listing '{listing_id}'"), 404
    return jsonify(listing)


@api.post("/listings/<path:listing_id>/status")
def listing_status(listing_id: str):
    config: Config = current_app.config["APP_CONFIG"]
    body = request.get_json(silent=True)
    error = _status_body_error(body)
    if error:
        return jsonify(error=error), 400
    with db.connection(config.db_path) as conn:
        if not db.update_status(conn, listing_id, body["status"]):
            return jsonify(error=f"Unknown listing '{listing_id}'"), 404
        if "note" in body:
            db.update_note(conn, listing_id, body["note"])
        return jsonify(db.get_listing(conn, listing_id, _profile_status(config)["hash"]))


def _status_body_error(body: object) -> str | None:
    if not isinstance(body, dict):
        return "Body must be a JSON object"
    if body.get("status") not in db.STATUS_VALUES:
        return f"status must be one of: {', '.join(db.STATUS_VALUES)}"
    if "note" in body and not isinstance(body["note"], (str, type(None))):
        return "note must be a string or null"
    return None


@api.post("/fetch")
def fetch():
    manager: FetchManager = current_app.config["FETCH_MANAGER"]
    key = request.args.get("source")
    if key is not None:
        return _fetch_one(manager, key)
    runnable = [entry.key for entry in manager.entries.values() if entry.runnable]
    started = [k for k in runnable if manager.start_in_background(k)]
    if runnable and not started:
        return jsonify(error="All enabled sources are already running"), 409
    return jsonify(started=started), 202


def _fetch_one(manager: FetchManager, key: str):
    entry = manager.entries.get(key)
    if entry is None:
        return jsonify(error=f"Unknown source '{key}'"), 404
    if not entry.runnable:
        return jsonify(error=f"Source '{key}' is disabled: {entry.error or 'enabled = false'}"), 400
    if not manager.start_in_background(key):
        return jsonify(error=f"Source '{key}' is already running"), 409
    return jsonify(started=[key]), 202


def _source_status(conn, entry: SourceEntry) -> dict:
    settings = entry.settings
    return {
        "key": entry.key,
        "enabled": entry.runnable,
        "config_error": entry.error,
        "running": entry.lock.locked(),
        "interval_minutes": settings.interval_minutes if settings else None,
        "last_run": db.last_run(conn, entry.key),
        "next_run_at": _next_run_at(entry.key),
    }


def _next_run_at(key: str) -> str | None:
    scheduler = current_app.config["SCHEDULER"]
    job = scheduler.get_job(key) if scheduler else None
    if job is None or job.next_run_time is None:
        return None
    return job.next_run_time.astimezone(UTC).isoformat(timespec="seconds")


def _profile_status(config: Config) -> dict:
    path = config.profile_path
    if not path.is_file():
        return {"present": False, "hash": None, "length": 0}
    data = path.read_bytes()
    return {
        "present": True,
        "hash": hashlib.sha256(data).hexdigest(),
        "length": len(data.decode("utf-8", errors="replace")),
    }
