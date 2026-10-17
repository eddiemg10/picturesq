"""`picturesq run` on real CC0 samples (needs reference/samples)."""

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from PIL.ExifTags import IFD, Base
from typer.testing import CliRunner

from picturesq.cli import app
from picturesq.config import ProjectConfig
from picturesq.decode import decode_original, read_capture_exif

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
        for output in ("web", "archive"):
            with Image.open(project / "exports" / output / f"{stem}.jpg") as exported:
                exif = exported.getexif()
            assert exif[Base.Make]
            assert exif[Base.Orientation] == 1
            assert exif.get_ifd(IFD.Exif)[Base.DateTimeOriginal]
            sidecar = json.loads(
                (project / "exports" / output / f"{stem}.picturesq.json").read_text()
            )
            assert sidecar["original"]["sha256"] == before[name]
        assert _sha256(project / name) == before[name]


@pytest.mark.parametrize(
    "name",
    [
        "dji-fc4382.dng",
        "pentax-k5iis.dng",
        "pentax-q7.dng",
        "sony-ilme-fx3.arw",
        "fujifilm-xq1.raf",
        "fujifilm-x-s10.raf",
    ],
)
def test_capture_exif_of_every_sample(samples_dir: Path, name: str) -> None:
    """TIFF-based originals are read directly, RAF through its embedded JPEG."""
    path = samples_dir / name
    if not path.exists():
        pytest.skip(f"{name} not found in {samples_dir}")
    capture = read_capture_exif(path)
    assert capture.image[Base.Make]
    assert capture.image[Base.Model]
    for tag in (Base.DateTimeOriginal, Base.ExposureTime, Base.FNumber, Base.ISOSpeedRatings):
        assert tag in capture.exif, tag.name
