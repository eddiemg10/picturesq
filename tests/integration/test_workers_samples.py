"""Exporting with several workers writes exactly what one worker writes (``pytest -m slow``)."""

from pathlib import Path

import pytest
from PIL import Image

from picturesq.config import ProjectConfig
from picturesq.decode import read_pixel_count
from picturesq.pipeline.export import export_originals
from picturesq.pipeline.workers import WorkerPlan, plan_workers

pytestmark = [pytest.mark.slow, pytest.mark.integration]

_NAMES = ("dji-fc4382.dng", "pentax-q7.dng")


def _files(folder: Path) -> dict[str, bytes]:
    return {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


def test_two_workers_write_identical_files_to_one(samples_dir: Path, tmp_path: Path) -> None:
    originals = [samples_dir / name for name in _NAMES]
    missing = [p.name for p in originals if not p.exists()]
    if missing:
        pytest.skip(f"{missing} not found in {samples_dir}")
    config = ProjectConfig()
    pixels = [read_pixel_count(original) for original in originals]

    def plan(max_photos: int) -> WorkerPlan:
        return plan_workers(pixels, cores=4, memory_budget=8 * 2**30, max_photos=max_photos)

    assert plan(2).workers == 2
    one = export_originals(originals, config, tmp_path / "one", plan=plan(1))
    two = export_originals(originals, config, tmp_path / "two", plan=plan(2))
    assert one.failed == two.failed == 0
    assert [p.name for p in two.photos] == list(_NAMES)
    expected, actual = _files(tmp_path / "one"), _files(tmp_path / "two")
    assert len(expected) == 4 * len(_NAMES)  # web + archive, each a JPEG and a sidecar
    assert actual.keys() == expected.keys()
    for name, data in expected.items():
        assert actual[name] == data, f"{name} differs between one and two workers"
    # The pixel count read before decoding bounds the decoded (and cropped) image.
    for original, photo in zip(originals, one.photos, strict=True):
        with Image.open(photo.outputs["archive"]) as archive:
            assert archive.width * archive.height <= read_pixel_count(original)
