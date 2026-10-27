"""The real export against the camera's own JPEG (ADR-0010), on a CC0 sample."""

from pathlib import Path

import pytest

from picturesq.config import ProjectConfig
from picturesq.decode import decode_original
from picturesq.decode.embedded import camera_jpeg
from picturesq.pipeline.export import render_output, render_scene
from picturesq.preview.compare import (
    MAX_EXTRA_CLIPPED,
    MAX_MEDIAN_EV,
    PhotoComparison,
    compare_photo,
)

pytestmark = pytest.mark.integration


def _dji_comparison(samples_dir: Path) -> PhotoComparison:
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
    return result


def test_dji_sample_clips_no_more_than_camera_jpeg(samples_dir: Path) -> None:
    result = _dji_comparison(samples_dir)
    assert result.clipped <= result.camera_clipped + MAX_EXTRA_CLIPPED


@pytest.mark.xfail(
    strict=True,
    reason=(
        "ADR-0018: without LibRaw's white level from the brightest pixel the sample decodes "
        "x1.09 darker and sits -0.56 EV from its camera JPEG; the exposure offset is fitted on "
        "the Pocket 4 set, which is unaffected. Revisit with the CC0 brightness gate (M2 close)."
    ),
)
def test_dji_sample_brightness_matches_camera_jpeg(samples_dir: Path) -> None:
    assert abs(_dji_comparison(samples_dir).ev_difference) <= MAX_MEDIAN_EV
