"""channel_mixer (black and white), vignette and grain."""

import numpy as np
import pytest
from pydantic import ValidationError

from picturesq.colour.spaces import REC2020_TO_XYZ
from picturesq.colour.transfer import srgb_decode, srgb_encode
from picturesq.config.operations import (
    ChannelMixerOperation,
    GrainOperation,
    VignetteOperation,
)
from picturesq.grade.operations import apply_operation, vignette_ev

SKY = np.array([0.08, 0.15, 0.35], dtype=np.float32)
SKIN = np.array([0.45, 0.25, 0.17], dtype=np.float32)


def _mono(colour: np.ndarray, operation: ChannelMixerOperation) -> np.ndarray:
    image = colour.copy()[None, None]
    return apply_operation(image, operation)[0, 0]


def test_mixer_keeps_greys() -> None:
    grey = np.full(3, 0.3, dtype=np.float32)
    mixed = _mono(grey, ChannelMixerOperation(red=1.2, green=-0.3, blue=0.4, amount=1.0))
    np.testing.assert_allclose(mixed, 0.3, rtol=1e-6)


def test_mixer_result_is_grey_and_weights_are_normalised() -> None:
    once = _mono(SKY, ChannelMixerOperation(red=0.5, green=0.3, blue=0.2, amount=1.0))
    twice = _mono(SKY, ChannelMixerOperation(red=1.0, green=0.6, blue=0.4, amount=1.0))
    assert np.ptp(once) < 1e-7
    np.testing.assert_allclose(once, twice, rtol=1e-6)


def test_default_weights_are_luminance() -> None:
    mixed = _mono(SKY, ChannelMixerOperation(amount=1.0))
    np.testing.assert_allclose(mixed, SKY @ REC2020_TO_XYZ[1], rtol=1e-3)


def test_red_filter_darkens_sky_and_lightens_skin() -> None:
    red_filter = ChannelMixerOperation(red=0.8, green=0.2, blue=0.0, amount=1.0)
    neutral = ChannelMixerOperation(amount=1.0)
    assert _mono(SKY, red_filter)[0] < _mono(SKY, neutral)[0]
    assert _mono(SKIN, red_filter)[0] > _mono(SKIN, neutral)[0]


def test_mixer_amount_blends_from_colour() -> None:
    full = _mono(SKY, ChannelMixerOperation(amount=1.0))
    half = _mono(SKY, ChannelMixerOperation(amount=0.5))
    np.testing.assert_allclose(half, 0.5 * (SKY + full), rtol=1e-6)


def test_mixer_weights_must_not_cancel() -> None:
    with pytest.raises(ValidationError, match=r"at least 0\.1"):
        ChannelMixerOperation(red=1.0, green=-1.0, blue=0.0)


def test_vignette_centre_untouched_corners_at_amount() -> None:
    operation = VignetteOperation(amount=-1.0, midpoint=0.4)
    ev = vignette_ev(401, 601, 0, 401, operation)
    assert ev[200, 300] == 0.0
    # Pixel centres at the corners sit just inside distance 1.
    assert ev[0, 0] == pytest.approx(-1.0, abs=0.01)
    np.testing.assert_allclose(ev, ev[::-1, ::-1], atol=1e-6)


def test_vignette_is_the_same_at_any_resolution() -> None:
    """Pixel i of an N-pixel image and pixel 3i+1 of a 3N one sit at the same position."""
    operation = VignetteOperation(amount=-0.8, midpoint=0.2, roundness=0.3)
    small = vignette_ev(40, 60, 0, 40, operation)
    large = vignette_ev(120, 180, 0, 120, operation)
    np.testing.assert_allclose(large[1::3, 1::3], small, atol=1e-6)


def test_vignette_roundness() -> None:
    """A circle through the corners of a wide frame darkens the middle of its short sides
    more than an ellipse with the frame's shape, and the middle of its long sides less."""
    circle = vignette_ev(100, 300, 50, 51, VignetteOperation(amount=-1.0, midpoint=0.0))
    ellipse = vignette_ev(
        100, 300, 50, 51, VignetteOperation(amount=-1.0, midpoint=0.0, roundness=0.0)
    )
    assert circle[0, 0] < ellipse[0, 0]  # the left side's middle
    top_circle = vignette_ev(100, 300, 0, 1, VignetteOperation(amount=-1.0, midpoint=0.0))
    top_ellipse = vignette_ev(
        100, 300, 0, 1, VignetteOperation(amount=-1.0, midpoint=0.0, roundness=0.0)
    )
    assert top_circle[0, 150] > top_ellipse[0, 150]  # the top side's middle


def _mid_grey(height: int = 300, width: int = 400) -> np.ndarray:
    return srgb_decode(np.full((height, width, 3), 0.46, dtype=np.float32))


def test_grain_is_seeded() -> None:
    operation = GrainOperation(amount=0.03)
    first = apply_operation(_mid_grey(), operation, seed=7)
    again = apply_operation(_mid_grey(), operation, seed=7)
    other = apply_operation(_mid_grey(), operation, seed=8)
    assert np.array_equal(first, again)
    assert not np.array_equal(first, other)


@pytest.mark.parametrize(("height", "width"), [(400, 800), (400, 2000), (400, 3000)])
def test_grain_strength_and_mean_in_the_mid_tones(height: int, width: int) -> None:
    """As strong at any size: fewer pixels than grain cells (2000 along the long edge),
    about as many, or more."""
    image = apply_operation(_mid_grey(height, width), GrainOperation(amount=0.03), seed=1)
    encoded = srgb_encode(image)
    assert encoded.mean() == pytest.approx(0.46, abs=0.002)
    assert encoded.std() == pytest.approx(0.03 * 4 * 0.46 * 0.54, rel=0.05)
    assert np.ptp(encoded, axis=-1).max() < 1e-5  # monochrome: the same on R, G and B


def test_grain_leaves_black_and_white() -> None:
    image = np.zeros((20, 30, 3), dtype=np.float32)
    image[10:] = 1.0
    before = image.copy()
    apply_operation(image, GrainOperation(amount=0.1), seed=3)
    np.testing.assert_allclose(image, before, atol=1e-6)


def test_grain_is_the_same_pattern_at_any_size() -> None:
    operation = GrainOperation(amount=0.03, size=0.005)
    small = srgb_encode(apply_operation(_mid_grey(60, 100), operation, seed=2))
    large = srgb_encode(apply_operation(_mid_grey(180, 300), operation, seed=2))
    np.testing.assert_allclose(large[1::3, 1::3], small, atol=1e-5)
