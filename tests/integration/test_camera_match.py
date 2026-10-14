"""The real export against the camera's own JPEG (ADR-0010), on a CC0 sample."""

from pathlib import Path

import pytest

from picturesq.config import ProjectConfig
from picturesq.decode import decode_original
from picturesq.decode.embedded import camera_jpeg
from picturesq.pipeline.export import render_output, render_scene
from picturesq.preview.compare import MAX_EXTRA_CLIPPED, MAX_MEDIAN_EV, compare_photo

pytestmark = pytest.mark.integration


def test_dji_sample_matches_camera_jpeg(samples_dir: Path) -> None:
    path = samples_dir / "dji-fc4382.dng"
    if not path.exists():
        pytest.skip(f"{path.name} not found in {samples_dir}")
    config = ProjectConfig()
    scene = render_scene(decode_original(path, config.decode, half_size=True), config)
    ours = render_output(scene, config.export.outputs["web"], config.grade.display_transform)
    jpeg = camera_jpeg(path)
    assert jpeg is not None
    result = compare_photo(path.name, ours, jpeg)
    assert result.same_frame
    assert abs(result.ev_difference) <= MAX_MEDIAN_EV
    assert result.clipped <= result.camera_clipped + MAX_EXTRA_CLIPPED
