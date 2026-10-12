import colour
import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from picturesq.colour.spaces import (
    REC709,
    REC709_TO_REC2020,
    REC709_TO_XYZ,
    REC2020,
    REC2020_TO_REC709,
    REC2020_TO_XYZ,
    XYZ_TO_REC709,
    XYZ_TO_REC2020,
    RgbSpace,
    apply_matrix,
    rgb_to_rgb_matrix,
)


def _derived(name: str) -> colour.RGB_Colourspace:
    """A colour-science space with matrices derived from its primaries (ADR-0008)."""
    space = colour.RGB_COLOURSPACES[name]
    return colour.RGB_Colourspace(
        f"{name} (derived)",
        space.primaries,
        space.whitepoint,
        use_derived_matrix_RGB_to_XYZ=True,
        use_derived_matrix_XYZ_to_RGB=True,
    )


ORACLE_REC2020 = _derived("ITU-R BT.2020")
ORACLE_REC709 = _derived("ITU-R BT.709")


# --- oracle --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ours", "expected"),
    [
        (REC2020_TO_XYZ, ORACLE_REC2020.matrix_RGB_to_XYZ),
        (XYZ_TO_REC2020, ORACLE_REC2020.matrix_XYZ_to_RGB),
        (REC709_TO_XYZ, ORACLE_REC709.matrix_RGB_to_XYZ),
        (XYZ_TO_REC709, ORACLE_REC709.matrix_XYZ_to_RGB),
        (REC2020_TO_REC709, colour.matrix_RGB_to_RGB(ORACLE_REC2020, ORACLE_REC709)),
        (REC709_TO_REC2020, colour.matrix_RGB_to_RGB(ORACLE_REC709, ORACLE_REC2020)),
    ],
)
def test_matrices_match_colour_science(ours: np.ndarray, expected: np.ndarray) -> None:
    np.testing.assert_allclose(ours, expected, atol=1e-6)


def test_rec709_to_rec2020_matches_itu_bt2087() -> None:
    # ITU-R BT.2087 publishes this matrix to 4 decimals.
    published = np.array(
        [[0.6274, 0.3293, 0.0433], [0.0691, 0.9195, 0.0114], [0.0164, 0.0880, 0.8956]]
    )
    np.testing.assert_allclose(REC709_TO_REC2020, published, atol=1e-4)


def test_published_srgb_matrix_is_close_but_not_white_exact() -> None:
    # Why ADR-0008 derives matrices: colour-science's default sRGB uses the rounded
    # published matrix, so white drifts by ~1e-4.
    published = colour.matrix_RGB_to_RGB(ORACLE_REC2020, colour.RGB_COLOURSPACES["sRGB"])
    np.testing.assert_allclose(REC2020_TO_REC709, published, atol=1e-3)
    assert np.abs(published.sum(axis=1) - 1).max() > 1e-5


# --- white and grey --------------------------------------------------------------------------


@pytest.mark.parametrize("matrix", [REC2020_TO_REC709, REC709_TO_REC2020])
def test_white_maps_to_white(matrix: np.ndarray) -> None:
    np.testing.assert_allclose(matrix @ np.ones(3), np.ones(3), atol=1e-12)


@pytest.mark.parametrize("matrix", [REC2020_TO_XYZ, REC709_TO_XYZ])
def test_white_has_luminance_one(matrix: np.ndarray) -> None:
    xyz = matrix @ np.ones(3)
    assert xyz[1] == pytest.approx(1.0, abs=1e-12)
    np.testing.assert_allclose(xyz[:2] / xyz.sum(), (0.3127, 0.3290), atol=1e-12)


def test_round_trip_is_identity() -> None:
    np.testing.assert_allclose(REC709_TO_REC2020 @ REC2020_TO_REC709, np.eye(3), atol=1e-12)


def test_different_white_points_raise() -> None:
    d50_space = RgbSpace("d50", REC709.red, REC709.green, REC709.blue, (0.3457, 0.3585))
    with pytest.raises(ValueError, match="white points"):
        rgb_to_rgb_matrix(REC2020, d50_space)


# --- gamut ----------------------------------------------------------------------------------


def test_rec709_fits_inside_rec2020() -> None:
    # Every Rec.709 colour is a valid (non-negative) Rec.2020 colour...
    assert np.all(REC709_TO_REC2020 >= 0)


def test_saturated_rec2020_green_is_outside_rec709() -> None:
    # ...but not the other way round: out-of-gamut colours come back negative.
    rgb = apply_matrix(np.array([0.0, 1.0, 0.0]), REC2020_TO_REC709)
    assert rgb[0] < 0
    assert rgb[2] < 0


# --- apply_matrix ---------------------------------------------------------------------------

IMAGES = arrays(
    np.float32,
    st.tuples(st.integers(1, 6), st.integers(1, 6), st.just(3)),
    elements=st.floats(-1.0, 16.0, width=32),
)


@given(IMAGES)
def test_apply_matrix_matches_per_pixel_matmul(image: np.ndarray) -> None:
    expected = np.einsum("ij,hwj->hwi", REC2020_TO_REC709, image.astype(np.float64))
    result = apply_matrix(image, REC2020_TO_REC709)
    assert result.dtype == np.float32
    np.testing.assert_allclose(result, expected, rtol=1e-5, atol=1e-5)


@given(IMAGES)
def test_apply_matrix_in_place(image: np.ndarray) -> None:
    expected = apply_matrix(image, REC2020_TO_REC709)
    buffer = image.copy()
    assert apply_matrix(buffer, REC2020_TO_REC709, out=buffer) is buffer
    np.testing.assert_array_equal(buffer, expected)


def test_apply_matrix_rejects_wrong_channel_count() -> None:
    with pytest.raises(ValueError, match="3 channels"):
        apply_matrix(np.zeros((2, 2, 4)), REC2020_TO_REC709)
