"""Blue rendering (ADR-0012): camera-matched skies, nothing else touched."""

import numpy as np
import pytest

from picturesq.colour.blue_rendering import blue_rendering, blue_rendering_weight
from picturesq.colour.oklab import oklab_to_rec709, rec709_to_oklab
from picturesq.config import BlueRenderingConfig, DisplayTransformConfig

DEFAULT = BlueRenderingConfig()


def _lch(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lab = rec709_to_oklab(rgb.astype(np.float32))
    return lab[:, 0], np.hypot(lab[:, 1], lab[:, 2]), np.degrees(np.arctan2(lab[:, 2], lab[:, 1]))


def _at_hue(hue: float, chroma: float = 0.08, lightness: float = 0.7) -> np.ndarray:
    angle = np.radians(hue)
    lab = np.array([[lightness, chroma * np.cos(angle), chroma * np.sin(angle)]], np.float32)
    return oklab_to_rec709(lab)


def test_on_by_default_and_can_be_turned_off() -> None:
    assert DisplayTransformConfig().blue_rendering.enabled
    sky = _at_hue(DEFAULT.hue)
    off = BlueRenderingConfig(enabled=False)
    np.testing.assert_array_equal(blue_rendering(sky.copy(), off), sky)


def test_greys_and_whites_untouched() -> None:
    greys = np.repeat(np.linspace(0.0, 1.0, 50, dtype=np.float32)[:, None], 3, axis=1)
    np.testing.assert_array_equal(blue_rendering(greys.copy(), DEFAULT), greys)


@pytest.mark.parametrize("hue", [30.0, 60.0, 110.0, 150.0])
def test_other_hues_untouched(hue: float) -> None:
    # Reds, oranges, yellows, greens: far outside the window around sky blue.
    colour = _at_hue(hue)
    np.testing.assert_array_equal(blue_rendering(colour.copy(), DEFAULT), colour)


def test_sky_blue_turns_cyan_deeper_and_more_colourful() -> None:
    sky = _at_hue(DEFAULT.hue, chroma=0.08, lightness=0.7)
    before = _lch(sky)
    after = _lch(blue_rendering(sky.copy(), DEFAULT))
    assert after[2][0] - before[2][0] == pytest.approx(DEFAULT.hue_shift, abs=0.05)
    assert after[1][0] / before[1][0] == pytest.approx(DEFAULT.chroma, rel=1e-3)
    assert after[0][0] / before[0][0] == pytest.approx(DEFAULT.lightness, rel=1e-3)


def test_weight_is_smooth_in_hue_and_chroma() -> None:
    hues = np.arange(0.0, 360.0, 1.0)
    lab = np.stack(
        [np.full_like(hues, 0.7), 0.1 * np.cos(np.radians(hues)), 0.1 * np.sin(np.radians(hues))], 1
    )
    weight = blue_rendering_weight(lab.astype(np.float32), DEFAULT)
    assert weight.max() == pytest.approx(1.0, abs=1e-3)
    assert np.abs(np.diff(weight)).max() < 0.05  # no hue banding
    chroma = np.linspace(0.0, 0.1, 101)
    lab = np.stack(
        [
            np.full_like(chroma, 0.7),
            chroma * np.cos(np.radians(250)),
            chroma * np.sin(np.radians(250)),
        ],
        1,
    )
    ramp = blue_rendering_weight(lab.astype(np.float32), DEFAULT)
    assert ramp[chroma <= DEFAULT.chroma_start].max() < 1e-9
    assert np.all(np.diff(ramp) >= 0.0)


def test_saturated_blues_stay_in_gamut_with_their_hue() -> None:
    rgb = np.array([[0.05, 0.2, 0.95], [0.1, 0.35, 1.0], [0.0, 0.1, 0.7]], np.float32)
    out = blue_rendering(rgb.copy(), BlueRenderingConfig(chroma=1.8, hue_shift=0.0))
    assert out.min() >= 0.0 and out.max() <= 1.0
    np.testing.assert_allclose(_lch(out)[2], _lch(rgb)[2], atol=0.2)
    np.testing.assert_allclose(_lch(out)[0], _lch(rgb)[0] * DEFAULT.lightness**1.0, atol=0.03)


def test_invalid_ramp_rejected() -> None:
    with pytest.raises(ValueError):
        BlueRenderingConfig(chroma_start=0.05, chroma_full=0.04)
