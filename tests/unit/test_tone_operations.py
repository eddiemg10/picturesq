"""Tone operations: tone_curve and fade."""

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from picturesq.colour.spaces import REC2020_TO_XYZ
from picturesq.colour.transfer import srgb_decode, srgb_encode
from picturesq.config.operations import MAX_INTENSITY, FadeOperation, ToneCurveOperation
from picturesq.grade import operations
from picturesq.grade.operations import CURVE_STEP_EV, apply_operation, tone_curve_table

SOFT_HIGHLIGHTS = ToneCurveOperation(points=((-2.0, -2.0), (0.0, 0.0), (2.0, 1.4), (4.0, 2.6)))


def _greys(evs: np.ndarray) -> np.ndarray:
    return np.repeat((0.18 * 2.0**evs)[:, None], 3, axis=1).astype(np.float32)[None]


def _stops(image: np.ndarray) -> np.ndarray:
    return np.log2((image @ REC2020_TO_XYZ[1].astype(np.float32))[0] / 0.18)


def test_curve_passes_through_its_points() -> None:
    xs = np.array([x for x, _ in SOFT_HIGHLIGHTS.points])
    image = apply_operation(_greys(xs), SOFT_HIGHLIGHTS)
    np.testing.assert_allclose(_stops(image), [y for _, y in SOFT_HIGHLIGHTS.points], atol=1e-4)


def test_curve_continues_straight_beyond_its_points() -> None:
    """Past the ends: the end secants (1 below, (2.6 - 1.4) / 2 = 0.6 above)."""
    image = apply_operation(_greys(np.array([-8.0, -6.0, 6.0, 8.0])), SOFT_HIGHLIGHTS)
    stops = _stops(image)
    np.testing.assert_allclose(stops[:2], [-8.0, -6.0], atol=1e-4)
    np.testing.assert_allclose(stops[2:], [3.8, 5.0], atol=1e-4)


def test_curve_is_smooth_at_its_ends() -> None:
    """The slope at an end point is its end secant, the tail's slope: no kink."""
    grid, shift = tone_curve_table(SOFT_HIGHLIGHTS.points)
    curve = shift + grid
    inside = (grid >= -2.0) & (grid <= 4.0)
    slope = np.diff(curve[inside]) / np.diff(grid[inside])
    assert slope[0] == pytest.approx(1.0, abs=0.02)
    assert slope[-1] == pytest.approx(0.6, abs=0.02)
    # Never steeper again past the softened part: the highlights stay soft.
    assert (slope[np.searchsorted(grid[inside], 2.0) :] < 0.85).all()


@settings(max_examples=60, deadline=None)
@given(
    steps=st.lists(st.tuples(st.floats(0.2, 3.0), st.floats(0.0, 3.0)), min_size=1, max_size=6),
    start=st.floats(-6.0, 0.0),
)
def test_monotone_points_give_a_monotone_curve(
    steps: list[tuple[float, float]], start: float
) -> None:
    """No overshoot: the curve never turns back, whatever monotone points it is given."""
    x, y, points = start, start, []
    for dx, dy in steps:
        points.append((x, y))
        x, y = x + dx, y + dy
    points.append((x, y))
    grid, shift = tone_curve_table(tuple(points))
    assert (np.diff(grid + shift) >= -1e-9).all()


def test_table_is_fine_enough(monkeypatch: pytest.MonkeyPatch) -> None:
    """Linear interpolation of the table is within 1e-4 EV of the cubic (a 64x finer table)."""
    grid, shift = tone_curve_table(SOFT_HIGHLIGHTS.points)
    monkeypatch.setattr(operations, "CURVE_STEP_EV", CURVE_STEP_EV / 64)
    fine_grid, fine_shift = tone_curve_table(SOFT_HIGHLIGHTS.points)
    coarse = np.interp(fine_grid, grid, shift)
    assert np.abs(coarse - fine_shift).max() < 1e-4


def test_curve_keeps_colour_ratios() -> None:
    image = np.array([[[0.6, 0.3, 0.1], [0.02, 0.05, 0.09]]], dtype=np.float32)
    ratios = image / image[..., 1:2]
    apply_operation(image, SOFT_HIGHLIGHTS)
    np.testing.assert_allclose(image / image[..., 1:2], ratios, rtol=1e-5)


def test_intensity_moves_outputs_toward_inputs() -> None:
    half = SOFT_HIGHLIGHTS.scaled(0.5)
    assert half.points[2] == (2.0, 1.7)
    assert SOFT_HIGHLIGHTS.scaled(0.0).is_neutral()
    assert ToneCurveOperation(points=((0.0, 0.0), (2.0, 2.0))).is_neutral()


def test_more_than_full_intensity_can_be_non_monotone_but_stays_finite() -> None:
    curve = ToneCurveOperation(points=((0.0, 0.0), (1.0, 1.0), (2.0, 1.0)))
    image = apply_operation(_greys(np.linspace(-4, 6, 40)), curve, MAX_INTENSITY)
    assert np.isfinite(image).all()


def test_one_point_shifts_every_tone() -> None:
    image = apply_operation(
        _greys(np.array([-3.0, 0.0, 3.0])), ToneCurveOperation(points=((0.0, 0.5),))
    )
    np.testing.assert_allclose(_stops(image), [-2.5, 0.5, 3.5], atol=1e-4)


@pytest.mark.parametrize(
    ("points", "message"),
    [
        (((0.0, 0.0), (0.0, 1.0)), "inputs must increase"),
        (((0.0, 1.0), (1.0, 0.5)), "must not decrease"),
        (((0.0, 0.0), (13.0, 13.0)), "less than or equal to 12"),
    ],
)
def test_invalid_points(points: tuple[tuple[float, float], ...], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        ToneCurveOperation(points=points)


def test_tone_curve_handles_black_and_negative_pixels() -> None:
    image = np.array([[[0.0, 0.0, 0.0], [-0.01, 0.02, 0.03]]], dtype=np.float32)
    apply_operation(image, SOFT_HIGHLIGHTS)
    assert np.isfinite(image).all()
    np.testing.assert_array_equal(image[0, 0], 0.0)


def test_fade_lifts_black_and_keeps_white() -> None:
    image = np.array([[[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]]], dtype=np.float32)
    apply_operation(image, FadeOperation(amount=0.05))
    np.testing.assert_allclose(srgb_encode(image.copy())[0, 0], 0.05, atol=1e-5)
    np.testing.assert_allclose(image[0, 1], 1.0, atol=1e-5)


def test_fade_mid_grey() -> None:
    grey = srgb_decode(np.full((1, 1, 3), 0.46, dtype=np.float32))
    apply_operation(grey, FadeOperation(amount=0.05))
    assert srgb_encode(grey)[0, 0, 0] == pytest.approx(0.05 + 0.95 * 0.46, abs=1e-5)


def test_fade_runs_after_the_display_transform() -> None:
    assert FadeOperation.space == "display"
    assert ToneCurveOperation.space == "scene"
