import json
from pathlib import Path

import pytest

from app import create_app
from app.config import Config

SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "jobsch"


@pytest.fixture
def load_sample():
    def _load(name: str) -> dict:
        path = SAMPLES / name
        if not path.is_file():
            pytest.skip(f"Sample {name} not available (samples/ is not in git)")
        return json.loads(path.read_text(encoding="utf-8"))

    return _load


@pytest.fixture
def make_app(tmp_path: Path):
    def _make(static_dir: Path | None = None):
        config = Config(
            db_path=tmp_path / "jobs.db",
            profile_path=tmp_path / "profile.md",
            sources_config=tmp_path / "sources.toml",
            static_dir=static_dir or tmp_path / "static",
            rating_backend="claude",
            claude_model="claude-haiku-5-5",
        )
        return create_app(config, start_scheduler=False)

    return _make
