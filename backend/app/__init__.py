"""Flask app factory."""

import logging
import tomllib
from datetime import UTC, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, abort, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from .api import api
from .config import Config, load_config, read_sources_file
from .db import init_db
from .fetcher import FetchManager

logger = logging.getLogger(__name__)


def create_app(config: Config | None = None, start_scheduler: bool = True) -> Flask:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = config or load_config()
    init_db(config.db_path)
    raw_sources, config_error = _read_sources(config)
    manager = FetchManager(config.db_path, raw_sources)

    app = Flask(__name__, static_folder=None)
    app.config["APP_CONFIG"] = config
    app.config["FETCH_MANAGER"] = manager
    app.config["SOURCES_CONFIG_ERROR"] = config_error
    app.config["SCHEDULER"] = _start_scheduler(manager) if start_scheduler else None
    app.register_blueprint(api)
    app.register_error_handler(HTTPException, _handle_http_error)
    _register_frontend(app, config)
    return app


def _read_sources(config: Config) -> tuple[dict, str | None]:
    """A broken sources file disables all sources but must not stop the app."""
    try:
        return read_sources_file(config.sources_config), None
    except (OSError, tomllib.TOMLDecodeError) as exc:
        logger.error("Cannot read %s: %s", config.sources_config, exc)
        return {}, f"Cannot read sources config: {exc}"


def _start_scheduler(manager: FetchManager) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    for key, entry in manager.entries.items():
        if not entry.runnable:
            continue
        startup = {"next_run_time": datetime.now(UTC)} if entry.settings.fetch_on_startup else {}
        scheduler.add_job(
            manager.run_scheduled,
            "interval",
            args=[key],
            id=key,
            minutes=entry.settings.interval_minutes,
            max_instances=1,
            coalesce=True,
            **startup,
        )
    scheduler.start()
    return scheduler


def _register_frontend(app: Flask, config: Config) -> None:
    """Serve the React build; unknown non-API paths fall back to index.html."""

    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def frontend(path: str):
        if path.startswith("api/"):
            abort(404)
        static_dir = config.static_dir
        if path and (static_dir / path).is_file():
            return send_from_directory(static_dir, path)
        if (static_dir / "index.html").is_file():
            return send_from_directory(static_dir, "index.html")
        return "Frontend not built. Run `npm run build` in frontend/.", 404


def _handle_http_error(err: HTTPException):
    """API errors are JSON; everything else keeps Flask's default page."""
    if request.path.startswith("/api/"):
        return jsonify(error=err.description), err.code
    return err
