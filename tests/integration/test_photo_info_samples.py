"""Photo info on real CC0 samples (needs reference/samples, see scripts/fetch_samples.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from picturesq.config.project import DecodeConfig
from picturesq.decode import decode_original, read_photo_info


def _sample(samples_dir: Path, name: str) -> Path:
    path = samples_dir / name
    if not path.is_file():
        pytest.skip(f"{name} not found in {samples_dir}")
    return path


def test_tungsten_interior_is_warm(samples_dir: Path) -> None:
    info = read_photo_info(_sample(samples_dir, "pentax-k5iis.dng"), DecodeConfig())
    assert info.as_shot_kelvin is not None
    assert info.as_shot_kelvin < 3500.0
    assert info.baseline_exposure_ev == pytest.approx(0.488, abs=1e-3)


def test_daylight_is_daylight(samples_dir: Path) -> None:
    info = read_photo_info(_sample(samples_dir, "dji-fc4382.dng"), DecodeConfig())
    assert info.as_shot_kelvin is not None
    assert 4500.0 < info.as_shot_kelvin < 7500.0
    assert info.as_shot_tint is not None
    assert abs(info.as_shot_tint) < 20.0


@pytest.mark.parametrize("name", ["fujifilm-xq1.raf", "sony-ilme-fx3.arw"])
def test_other_raws_have_an_as_shot_white(samples_dir: Path, name: str) -> None:
    info = read_photo_info(_sample(samples_dir, name), DecodeConfig())
    assert info.as_shot_kelvin is not None
    assert 4000.0 < info.as_shot_kelvin < 7000.0
    assert info.baseline_exposure_ev == 0.0


@pytest.mark.parametrize("name", ["fujifilm-xq1.raf", "pentax-k5iis.dng"])
@pytest.mark.parametrize("mode", ["clip", "blend"])
def test_clip_level_is_where_the_decode_clips(samples_dir: Path, name: str, mode: str) -> None:
    # Both samples have sensor-clipped highlights; the brightest clipped white is the pixel
    # whose smallest channel is largest.
    path = _sample(samples_dir, name)
    config = DecodeConfig(highlight_mode=mode)  # type: ignore[arg-type]
    image = decode_original(path, config, half_size=True)
    measured = float(image.min(axis=-1).max())
    del image
    assert read_photo_info(path, config).clip_level == pytest.approx(measured, rel=0.02)
