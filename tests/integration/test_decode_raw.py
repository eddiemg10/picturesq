"""Decode real CC0 samples (needs reference/samples, see scripts/fetch_samples.py)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from picturesq.config.project import DecodeConfig
from picturesq.decode import decode_original

pytestmark = pytest.mark.integration

SAMPLES = ["fujifilm-x-s10.raf", "sony-ilme-fx3.arw", "pentax-k5iis.dng", "dji-fc4382.dng"]

# Neutral grey patches on the IT8 chart in fujifilm-x-s10.raf (grey ramp at the bottom), as
# (x0, x1, y0, y1) fractions of width/height. Measured (half-size): R/G 1.04, B/G 0.94 for the
# first, R/G 1.03, B/G 0.96 for the second. As-shot white balance isn't perfect and the print
# tints slightly warm, hence the tolerance.
GREY_PATCHES = [(0.240, 0.265, 0.785, 0.855), (0.340, 0.365, 0.785, 0.855)]
RATIO_TOLERANCE = 0.08


def _sample(samples_dir: Path, name: str) -> Path:
    path = samples_dir / name
    if not path.exists():
        pytest.skip(f"{name} not found in {samples_dir}")
    return path


@pytest.mark.parametrize("name", SAMPLES)
def test_half_size_decode_is_scene_linear_float32(samples_dir: Path, name: str) -> None:
    image = decode_original(_sample(samples_dir, name), DecodeConfig(), half_size=True)
    assert image.dtype == np.float32
    assert image.ndim == 3
    assert image.shape[2] == 3
    assert image.flags.c_contiguous
    assert np.isfinite(image).all()
    assert image.min() >= 0.0
    assert image.max() <= 1.0


def test_full_size_decode_is_twice_half_size(samples_dir: Path) -> None:
    path = _sample(samples_dir, "dji-fc4382.dng")
    half = decode_original(path, DecodeConfig(), half_size=True)
    full = decode_original(path, DecodeConfig())
    assert full.dtype == np.float32
    assert abs(full.shape[0] - 2 * half.shape[0]) <= 2
    assert abs(full.shape[1] - 2 * half.shape[1]) <= 2


@pytest.mark.parametrize("half_size", [True, False])
def test_grey_patches_stay_neutral(samples_dir: Path, half_size: bool) -> None:
    image = decode_original(
        _sample(samples_dir, "fujifilm-x-s10.raf"), DecodeConfig(), half_size=half_size
    )
    height, width, _ = image.shape
    for x0, x1, y0, y1 in GREY_PATCHES:
        patch = image[int(y0 * height) : int(y1 * height), int(x0 * width) : int(x1 * width)]
        r, g, b = patch.reshape(-1, 3).mean(axis=0)
        assert r / g == pytest.approx(1.0, abs=RATIO_TOLERANCE)
        assert b / g == pytest.approx(1.0, abs=RATIO_TOLERANCE)
