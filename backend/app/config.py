"""App-wide settings from environment variables; raw per-source settings from TOML."""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@dataclass(frozen=True)
class Config:
    db_path: Path
    profile_path: Path
    sources_config: Path
    static_dir: Path
    rating_backend: str
    claude_model: str


def load_config() -> Config:
    env = os.environ
    return Config(
        db_path=Path(env.get("DB_PATH", "/data/jobs.db")),
        profile_path=Path(env.get("PROFILE_PATH", "/data/profile.md")),
        sources_config=Path(env.get("SOURCES_CONFIG", "/data/sources.toml")),
        static_dir=Path(env.get("STATIC_DIR", str(DEFAULT_STATIC_DIR))),
        rating_backend=env.get("RATING_BACKEND", "claude"),
        claude_model=env.get("CLAUDE_MODEL", "claude-haiku-5-5"),
    )


def read_sources_file(path: Path) -> dict:
    """Return the raw tables of sources.toml; a missing file means no sources."""
    if not path.is_file():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)
