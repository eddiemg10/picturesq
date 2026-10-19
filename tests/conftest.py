"""Shared test fixtures."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def samples_dir() -> Path:
    """Directory of CC0 sample originals (``PICTURESQ_SAMPLES`` overrides ``reference/samples``)."""
    path = Path(os.environ.get("PICTURESQ_SAMPLES", _REPO_ROOT / "reference" / "samples"))
    if not path.is_dir():
        pytest.skip(f"sample originals not found at {path} (run scripts/fetch_samples.py)")
    return path


TEST_LOOKS: dict[str, dict[str, object]] = {
    "cold/test_cool": {
        "name": "test_cool",
        "category": "cold",
        "description": "A test look: cooler, more contrast, faded",
        "parameters": {"fade": {"default": 0.05, "min": 0.0, "max": 0.2, "label": "Fade"}},
        "operations": [
            {"op": "white_balance", "warmth": -20},
            {"op": "contrast", "amount": 0.2},
            {"op": "fade", "amount": "$fade"},
        ],
    },
    "bw/test_mono": {
        "name": "test_mono",
        "category": "bw",
        "description": "A test look: red-filter black and white with grain",
        "operations": [
            {"op": "channel_mixer", "red": 0.7, "green": 0.3, "blue": 0.0, "amount": 1.0},
            {"op": "grain", "amount": 0.03},
        ],
    },
}


@pytest.fixture
def test_looks(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):
    """Replace the built-in look library with ``TEST_LOOKS`` (this process only)."""
    import yaml

    from picturesq.config import look

    directory = tmp_path_factory.mktemp("looks")
    for key, content in TEST_LOOKS.items():
        path = directory / f"{key}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(content), encoding="utf-8")
    library = look.load_looks(directory)
    monkeypatch.setattr(look, "look_library", lambda: library)
    return library
