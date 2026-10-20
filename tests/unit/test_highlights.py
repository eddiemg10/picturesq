"""The highlights operation: darken (or brighten) the bright areas only, keeping detail."""

import numpy as np
import pytest
from pydantic import ValidationError

from picturesq.colour.transfer import MIDDLE_GREY
from picturesq.config import AdjustmentsConfig
from picturesq.config.operations import HIGHLIGHTS_FULL_CHANGE, HighlightsOperation
from picturesq.grade import adjustment_operations
from picturesq.grade.operations import apply_operation, highlights_ev


def _scene(height: int = 120, width: int = 180) -> np.ndarray:
    """Mid grey on the left, a bright 'screen' (+5 EV) with a fine checker on the right."""
    image = np.full((height, width, 3), MIDDLE_GREY, dtype=np.float32)
    screen = MIDDLE_GREY * 2.0**5
    image[:, width // 2 :] = screen
    checker = (np.indices((height, width - width // 2)).sum(axis=0) % 2).astype(bool)
    image[:, width // 2 :][checker] *= 2.0**0.5  # half a stop of detail on the screen
    return image


def _stops(after: np.ndarray, before: np.ndarray) -> np.ndarray:
    return np.log2(after[..., 1] / before[..., 1])


def test_zero_is_untouched_bit_for_bit() -> None:
    image = _scene()
    out = apply_operation(image.copy(), HighlightsOperation(amount=0.0))
    np.testing.assert_array_equal(out, image)
    assert HighlightsOperation().is_neutral()


def test_curve_far_above_start_has_the_compressed_slope() -> None:
    operation = HighlightsOperation(amount=-1.0, start_ev=1.0)
    base = np.array([5.0, 6.0], dtype=np.float32)
    change = highlights_ev(base.copy(), operation)
    slope = 1.0 + float(change[1] - change[0])
    assert slope == pytest.approx(1.0 - HIGHLIGHTS_FULL_CHANGE, abs=1e-3)


def test_curve_is_zero_up_to_the_start_and_smooth_after() -> None:
    operation = HighlightsOperation(amount=-1.0, start_ev=1.5)
    base = np.linspace(-4.0, 1.5, 50, dtype=np.float32)
    np.testing.assert_array_equal(highlights_ev(base, operation), 0.0)
    ramp = highlights_ev(np.linspace(1.5, 8.0, 651, dtype=np.float32), operation)
    slope = np.diff(ramp) / 0.01
    assert np.all(np.diff(slope) <= 1e-3)  # only ever steeper: no kink back
    assert np.abs(np.diff(slope)).max() < 0.01  # no corner


def test_bright_area_darkens_mid_grey_stays() -> None:
    image = _scene()
    out = apply_operation(image.copy(), HighlightsOperation(amount=-0.8))
    stops = _stops(out, image)
    width = image.shape[1]
    assert np.abs(stops[:, : width // 2 - 10]).max() < 0.01
    # Base ~5.25 EV: (5.25 - 1.5 - 0.75) stops above the knee, times 0.8 * 0.8.
    np.testing.assert_allclose(stops[:, width // 2 + 10 :], -1.92, atol=0.06)


def test_detail_on_the_bright_area_is_kept() -> None:
    image = _scene()
    out = apply_operation(image.copy(), HighlightsOperation(amount=-1.0))
    width = image.shape[1]
    region = (slice(20, 100), slice(width // 2 + 20, width - 20))
    before = np.log2(image[region][..., 1])
    after = np.log2(out[region][..., 1])
    # The checker's half stop survives (the gain is set by the area, not each pixel).
    assert np.ptp(after) == pytest.approx(np.ptp(before), abs=0.05)


def test_colour_ratios_are_kept() -> None:
    image = _scene()
    image[..., 0] *= 1.5
    out = apply_operation(image.copy(), HighlightsOperation(amount=-1.0))
    np.testing.assert_allclose(out[..., 0] / out[..., 1], image[..., 0] / image[..., 1], rtol=1e-5)


def test_positive_brightens() -> None:
    image = _scene()
    out = apply_operation(image.copy(), HighlightsOperation(amount=0.5))
    assert _stops(out, image)[:, -20:].min() > 1.0


def test_same_result_at_any_resolution() -> None:
    small = _scene(120, 180)
    large = _scene(360, 540)
    operation = HighlightsOperation(amount=-0.8)
    small_stops = _stops(apply_operation(small.copy(), operation), small)
    large_stops = _stops(apply_operation(large.copy(), operation), large)
    # Compare the middle of each half (edges differ by a pixel or two of blur).
    assert np.median(small_stops[:, 150:170]) == pytest.approx(
        np.median(large_stops[:, 450:510]), abs=0.05
    )


def test_adjustment_runs_the_operation() -> None:
    operations = adjustment_operations(AdjustmentsConfig(highlights=-0.5))
    assert HighlightsOperation(amount=-0.5) in operations


def test_range_is_checked() -> None:
    with pytest.raises(ValidationError):
        AdjustmentsConfig(highlights=-1.5)
    with pytest.raises(ValidationError):
        HighlightsOperation(radius=0.0)
