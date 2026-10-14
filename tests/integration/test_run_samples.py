"""`picturesq run` on real CC0 samples (needs reference/samples)."""

import hashlib
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from typer.testing import CliRunner

from picturesq.cli import app
from picturesq.config import ProjectConfig
from picturesq.decode import decode_original

pytestmark = pytest.mark.integration

SAMPLES = ["dji-fc4382.dng", "sony-ilme-fx3.arw"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_run_on_samples(samples_dir: Path, tmp_path: Path) -> None:
    for name in SAMPLES:
        if not (samples_dir / name).exists():
            pytest.skip(f"{name} not found in {samples_dir}")
    project = tmp_path / "project"
    project.mkdir()
    for name in SAMPLES:
        shutil.copy(samples_dir / name, project / name)
    before = {name: _sha256(project / name) for name in SAMPLES}

    result = CliRunner().invoke(app, ["run", str(project)])
    assert result.exit_code == 0, result.output

    for name in SAMPLES:
        stem = Path(name).stem
        decoded = decode_original(project / name, ProjectConfig().decode, half_size=False)
        height, width = decoded.shape[:2]
        with Image.open(project / "exports" / "web" / f"{stem}.jpg") as web:
            assert max(web.size) == 2048
            web_pixels = np.asarray(web)
        with Image.open(project / "exports" / "archive" / f"{stem}.jpg") as archive:
            assert archive.size == (width, height)
            archive_pixels = np.asarray(archive)
        for pixels in (web_pixels, archive_pixels):
            assert 5 < pixels.mean() < 250
            assert pixels.std() > 0
        assert _sha256(project / name) == before[name]
