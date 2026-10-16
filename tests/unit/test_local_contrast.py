"""Local contrast: detail is amplified where the curve is flat; broad tones and edges are not."""

import numpy as np
import pytest

from picturesq.colour.transfer import MIDDLE_GREY
from picturesq.config import DisplayTransformConfig, LocalContrastConfig
from picturesq.grade.local_contrast import curve_slope, local_contrast

DISPLAY = DisplayTransformConfig()
SIZE = 256


def _grey(ev: np.ndarray) -> np.ndarray:
    """A grey image whose luminance is ``ev`` stops from mid grey, per pixel."""
    value = (MIDDLE_GREY * 2.0**ev).astype(np.float32)
    return np.repeat(value[..., None], 3, axis=-1)


def _ripple(base_ev: float, amplitude: float = 0.1) -> np.ndarray:
    x = np.arange(SIZE, dtype=np.float32)
    detail = amplitude * np.sin(2 * np.pi * x / 8.0)  # 8 px period: fine detail
    return np.broadcast_to(base_ev + detail[None, :], (SIZE, SIZE)).copy()


def _ev(image: np.ndarray) -> np.ndarray:
    return np.log2(image[..., 1] / MIDDLE_GREY)


def test_slope_at_mid_grey_is_the_contrast() -> None:
    ev, slope = curve_slope(DISPLAY)
    at_grey = float(np.interp(0.0, ev, slope))
    assert at_grey == pytest.approx(DISPLAY.contrast, abs=0.05)
    assert float(np.interp(4.0, ev, slope)) < 0.3  # the shoulder is flat


def test_disabled_changes_nothing() -> None:
    image = _grey(_ripple(3.5))
    before = image.copy()
    local_contrast(image, LocalContrastConfig(enabled=False), DISPLAY)
    np.testing.assert_array_equal(image, before)


@pytest.mark.parametrize("ev", [-3.0, 0.0, 3.5])
def test_flat_image_is_unchanged(ev: float) -> None:
    image = _grey(np.full((64, 96), ev, dtype=np.float32))
    before = image.copy()
    local_contrast(image, LocalContrastConfig(), DISPLAY)
    np.testing.assert_allclose(image, before, rtol=1e-4)


def test_detail_in_a_bright_sky_is_amplified_to_the_floor() -> None:
    config = LocalContrastConfig(amount=1.0)
    image = _grey(_ripple(3.5))
    local_contrast(image, config, DISPLAY)
    ev, slope = curve_slope(DISPLAY)
    expected = min(config.detail_floor / float(np.interp(3.5, ev, slope)), config.max_gain)
    centre = _ev(image)[SIZE // 2, SIZE // 4 : 3 * SIZE // 4]
    assert np.ptp(centre) / 0.2 == pytest.approx(expected, rel=0.1)
    assert float(centre.mean()) == pytest.approx(3.5, abs=0.02)  # the broad tone is kept


def test_midtone_detail_gets_only_the_amount() -> None:
    image = _grey(_ripple(0.0))
    local_contrast(image, LocalContrastConfig(amount=1.15), DISPLAY)
    centre = _ev(image)[SIZE // 2, SIZE // 4 : 3 * SIZE // 4]
    assert np.ptp(centre) / 0.2 == pytest.approx(1.15, rel=0.05)


def test_a_horizon_gets_no_halo() -> None:
    # Dark ground (-2 EV) under a bright, flat sky (+4 EV): a 6-stop edge, no detail.
    ev = np.where(np.arange(SIZE)[:, None] < SIZE // 2, 4.0, -2.0) * np.ones((1, SIZE))
    image = _grey(ev.astype(np.float32))
    local_contrast(image, LocalContrastConfig(), DISPLAY)
    assert np.abs(_ev(image) - ev).max() < 0.15


def test_colour_ratios_are_kept() -> None:
    ev = _ripple(3.0, amplitude=0.3)
    image = _grey(ev) * np.array([0.6, 1.0, 1.4], dtype=np.float32)
    ratios = image / image[..., 1:2]
    local_contrast(image, LocalContrastConfig(), DISPLAY)
    np.testing.assert_allclose(image / image[..., 1:2], ratios, rtol=1e-5)


def test_large_detail_is_amplified_less_than_small() -> None:
    config = LocalContrastConfig(amount=1.0)
    small, large = _grey(_ripple(3.5, 0.1)), _grey(_ripple(3.5, 2.0))
    local_contrast(small, config, DISPLAY)
    local_contrast(large, config, DISPLAY)
    row = slice(SIZE // 4, 3 * SIZE // 4)
    small_gain = np.ptp(_ev(small)[SIZE // 2, row]) / 0.2
    large_gain = np.ptp(_ev(large)[SIZE // 2, row]) / 4.0
    assert large_gain < 1.5 < small_gain
