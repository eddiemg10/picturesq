"""Colour temperature, tint and Bradford adaptation, checked against colour-science."""

import colour
import numpy as np
import pytest
from colour.temperature import robertson1968
from hypothesis import given, settings
from hypothesis import strategies as st

from picturesq.colour.spaces import D65, REC2020_TO_XYZ, XYZ_TO_REC2020
from picturesq.colour.temperature import (
    _ROBERTSON,
    bradford_matrix,
    kelvin_tint_to_xy,
    mired,
    white_balance_matrix,
    xy_to_cct,
    xy_to_kelvin_tint,
    xy_to_xyz,
)


def test_isotemperature_table_matches_colour_science() -> None:
    expected = np.array(robertson1968.DATA_ISOTEMPERATURE_LINES_ROBERTSON1968)
    assert np.allclose(_ROBERTSON, expected, atol=0, rtol=0)


@pytest.mark.parametrize(
    "xy",
    [
        (0.3127, 0.3290),
        (0.44757, 0.40745),
        (0.3457, 0.3585),
        (0.28, 0.29),
        (0.38, 0.38),
        (0.50, 0.41),
    ],
)
def test_cct_matches_colour_science(xy: tuple[float, float]) -> None:
    uv = colour.xy_to_UCS_uv(np.array(xy))
    expected = robertson1968.uv_to_CCT_Robertson1968(uv)[0]
    assert xy_to_cct(xy) == pytest.approx(expected, rel=1e-6)


def test_bradford_maps_white_to_white_and_matches_colour_science() -> None:
    a, d65 = (0.44757, 0.40745), (0.3127, 0.3290)
    matrix = bradford_matrix(a, d65)
    assert np.allclose(matrix @ xy_to_xyz(a), xy_to_xyz(d65), atol=1e-12)
    expected = colour.adaptation.matrix_chromatic_adaptation_VonKries(
        xy_to_xyz(a), xy_to_xyz(d65), transform="Bradford"
    )
    assert np.allclose(matrix, expected, atol=1e-9)


# --- White balance: kelvin and tint, mired, re-balancing matrix ---------------------------


@pytest.mark.parametrize(
    "kelvin", [1700.0, 2000.0, 2850.0, 4000.0, 5003.0, 6504.0, 9000.0, 12000.0, 25000.0]
)
@pytest.mark.parametrize("tint", [-50.0, -10.0, 0.0, 10.0, 50.0])
def test_kelvin_tint_to_xy_matches_colour_science(kelvin: float, tint: float) -> None:
    # colour-science's Duv is positive above the locus (green); our tint is -1000 * Duv.
    uv = robertson1968.CCT_to_uv_Robertson1968(np.array([kelvin, -tint / 1000.0]))
    expected = colour.UCS_uv_to_xy(uv)
    assert np.allclose(kelvin_tint_to_xy(kelvin, tint), expected, atol=1e-12)


@pytest.mark.parametrize(
    "xy", [(0.3127, 0.3290), (0.44757, 0.40745), (0.3457, 0.3585), (0.30, 0.34), (0.40, 0.36)]
)
def test_xy_to_kelvin_tint_matches_colour_science(xy: tuple[float, float]) -> None:
    kelvin, duv = robertson1968.uv_to_CCT_Robertson1968(colour.xy_to_UCS_uv(np.array(xy)))
    ours = xy_to_kelvin_tint(xy)
    assert ours[0] == pytest.approx(kelvin, rel=1e-6)
    assert ours[1] == pytest.approx(-1000.0 * duv, abs=1e-6)
    assert ours[0] == pytest.approx(xy_to_cct(xy))


def test_tint_direction_positive_is_magenta() -> None:
    # Below the Planckian locus, a magenta white has relatively less green: lower y.
    _, neutral_y = kelvin_tint_to_xy(5500.0, 0.0)
    _, magenta_y = kelvin_tint_to_xy(5500.0, 20.0)
    _, green_y = kelvin_tint_to_xy(5500.0, -20.0)
    assert green_y > neutral_y > magenta_y


def test_d65_is_slightly_green_of_the_locus() -> None:
    kelvin, tint = xy_to_kelvin_tint((0.3127, 0.3290))
    assert kelvin == pytest.approx(6504, abs=2)
    assert tint == pytest.approx(-3.2, abs=0.1)  # Duv ~ +0.0032, above the locus


@settings(max_examples=300, deadline=None)
@given(
    kelvin=st.floats(min_value=2000.0, max_value=12000.0),
    tint=st.floats(min_value=-50.0, max_value=50.0),
)
def test_kelvin_tint_round_trip(kelvin: float, tint: float) -> None:
    back_kelvin, back_tint = xy_to_kelvin_tint(kelvin_tint_to_xy(kelvin, tint))
    assert back_kelvin == pytest.approx(kelvin, abs=1.0)
    assert back_tint == pytest.approx(tint, abs=0.1)


def test_kelvin_below_the_table_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least 1667"):
        kelvin_tint_to_xy(1500.0, 0.0)


def test_mired() -> None:
    assert mired(5000.0) == pytest.approx(200.0)
    assert mired(5000.0) == pytest.approx(float(robertson1968.CCT_to_mired(5000.0)))
    # Same 500 K step, very different visual size.
    assert mired(2000.0) - mired(2500.0) == pytest.approx(100.0)
    assert mired(10000.0) - mired(10500.0) < 5.0
    with pytest.raises(ValueError):
        mired(0.0)


def test_white_balance_matrix_identity_when_whites_are_equal() -> None:
    assert np.allclose(white_balance_matrix(D65, D65), np.eye(3), atol=1e-12)


@settings(max_examples=100, deadline=None)
@given(
    source=st.tuples(st.floats(2000.0, 12000.0), st.floats(-50.0, 50.0)),
    target=st.tuples(st.floats(2000.0, 12000.0), st.floats(-50.0, 50.0)),
)
def test_white_balance_matrix_maps_source_white_to_target_white(
    source: tuple[float, float], target: tuple[float, float]
) -> None:
    source_xy, target_xy = kelvin_tint_to_xy(*source), kelvin_tint_to_xy(*target)
    matrix = white_balance_matrix(source_xy, target_xy)
    source_rgb = XYZ_TO_REC2020 @ xy_to_xyz(source_xy)
    target_rgb = XYZ_TO_REC2020 @ xy_to_xyz(target_xy)
    assert np.allclose(matrix @ source_rgb, target_rgb, atol=1e-12)
    assert matrix.dtype == np.float64


def test_white_balance_matrix_matches_colour_science() -> None:
    tungsten = kelvin_tint_to_xy(2850.0, 0.0)
    adaptation = colour.adaptation.matrix_chromatic_adaptation_VonKries(
        xy_to_xyz(tungsten), xy_to_xyz(D65), transform="Bradford"
    )
    expected = XYZ_TO_REC2020 @ adaptation @ REC2020_TO_XYZ
    assert np.allclose(white_balance_matrix(tungsten, D65), expected, atol=1e-9)
    # A grey card lit by tungsten becomes neutral (R = G = B) under D65.
    grey_under_tungsten = XYZ_TO_REC2020 @ (0.18 * xy_to_xyz(tungsten))
    assert np.allclose(white_balance_matrix(tungsten, D65) @ grey_under_tungsten, 0.18, atol=1e-12)
