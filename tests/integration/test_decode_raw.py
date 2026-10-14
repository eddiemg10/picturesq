"""Decode real CC0 samples (needs reference/samples, see scripts/fetch_samples.py)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rawpy
from rawpy._rawpy import ColorSpace, HighlightMode

from picturesq.config.project import DecodeConfig
from picturesq.decode import decode_original, read_baseline_exposure

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
    # Out-of-gamut colours keep a negative channel (#47), but nothing is negative overall.
    assert image.sum(axis=-1).min() >= -0.05
    # BaselineExposure can lift values above 1.0 (scene-linear headroom), so no upper bound of 1.
    assert image.max() > 0.0


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


def test_baseline_exposure_read_from_dng(samples_dir: Path) -> None:
    ev = read_baseline_exposure(_sample(samples_dir, "dji-fc4382.dng"))
    assert ev == pytest.approx(1.32, abs=0.01)


def test_baseline_exposure_zero_for_raf(samples_dir: Path) -> None:
    assert read_baseline_exposure(_sample(samples_dir, "fujifilm-x-s10.raf")) == 0.0


def test_baseline_exposure_decode_is_linear_gain(samples_dir: Path) -> None:
    path = _sample(samples_dir, "dji-fc4382.dng")
    ev = read_baseline_exposure(path)
    on = decode_original(path, DecodeConfig(baseline_exposure=True), half_size=True)
    off = decode_original(path, DecodeConfig(baseline_exposure=False), half_size=True)
    assert on.max() > off.max()
    np.testing.assert_allclose(on, off * np.float32(2.0**ev), rtol=1e-5, atol=1e-6)


@pytest.mark.parametrize("name", ["sony-ilme-fx3.arw", "dji-fc4382.dng"])
def test_matches_libraw_rec2020_for_in_gamut_colours(samples_dir: Path, name: str) -> None:
    """Our float camera → Rec.2020 conversion agrees with LibRaw's own where LibRaw can't clip."""
    path = _sample(samples_dir, name)
    ours = decode_original(path, DecodeConfig(baseline_exposure=False), half_size=True)
    with rawpy.imread(str(path)) as raw:
        libraw = raw.postprocess(
            half_size=True,
            use_camera_wb=True,
            no_auto_bright=True,
            gamma=(1, 1),
            output_bps=16,
            output_color=ColorSpace.Rec2020,
            highlight_mode=HighlightMode.Blend,
        ).astype(np.float32) / np.float32(65535.0)
    in_gamut = ((ours > 0.002) & (ours < 0.9)).all(axis=-1)
    error = np.abs(ours[in_gamut] - libraw[in_gamut]).max(axis=-1) / libraw[in_gamut].max(axis=-1)
    assert np.percentile(error, 99) < 0.01


def test_out_of_gamut_colours_survive(samples_dir: Path) -> None:
    """#47: LibRaw's integer output clipped ~13 % of the Sony sample's pixels to a zero channel."""
    image = decode_original(
        _sample(samples_dir, "sony-ilme-fx3.arw"), DecodeConfig(), half_size=True
    )
    assert (image.min(axis=-1) == 0.0).mean() < 0.001
    assert (image.min(axis=-1) < 0.0).mean() > 0.05
