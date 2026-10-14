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
