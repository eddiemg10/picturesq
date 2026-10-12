import colour
import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from picturesq.colour.transfer import (
    EV_FLOOR,
    MIDDLE_GREY,
    SRGB_LINEAR_BREAK,
    ev_to_linear,
    linear_to_ev,
    srgb_decode,
    srgb_encode,
)


def _float32_arrays(min_value: float, max_value: float) -> st.SearchStrategy[np.ndarray]:
    return arrays(
        np.float32,
        st.tuples(st.integers(1, 8), st.integers(1, 8), st.just(3)),
        elements=st.floats(min_value, max_value, width=32),
    )


# Display range plus the extensions we keep: out-of-gamut negatives and highlights above 1.
SCENE_VALUES = _float32_arrays(-0.5, 16.0)


# --- sRGB: oracle --------------------------------------------------------------------------


@given(SCENE_VALUES)
def test_srgb_encode_matches_colour_science(image: np.ndarray) -> None:
    expected = colour.cctf_encoding(image.astype(np.float64), function="sRGB")
    np.testing.assert_allclose(srgb_encode(image), expected, rtol=1e-6, atol=1e-6)


@given(_float32_arrays(-0.5, 4.0))
def test_srgb_decode_matches_colour_science(image: np.ndarray) -> None:
    expected = colour.cctf_decoding(image.astype(np.float64), function="sRGB")
    np.testing.assert_allclose(srgb_decode(image), expected, rtol=1e-6, atol=1e-6)


@pytest.mark.parametrize(
    ("linear", "encoded"),
    [
        (0.0, 0.0),
        (1.0, 1.0),
        (SRGB_LINEAR_BREAK, 0.0404499),  # the break: both segments agree here
        (0.18, 0.4613561),  # mid grey lands at ~118/255, not 128
    ],
)
def test_srgb_known_values(linear: float, encoded: float) -> None:
    value = np.array([linear], dtype=np.float64)
    np.testing.assert_allclose(srgb_encode(value), [encoded], atol=1e-6)


def test_srgb_is_not_gamma_2_2_in_the_shadows() -> None:
    shadow = np.array([0.001])
    assert srgb_encode(shadow)[0] < 0.5 * shadow[0] ** (1 / 2.2)


# --- sRGB: round trip and array behaviour --------------------------------------------------


@given(SCENE_VALUES)
def test_srgb_round_trip(image: np.ndarray) -> None:
    restored = srgb_decode(srgb_encode(image))
    np.testing.assert_allclose(restored, image, rtol=1e-6, atol=1e-6)


@given(SCENE_VALUES)
def test_srgb_in_place_matches_out_of_place(image: np.ndarray) -> None:
    expected = srgb_encode(image)
    buffer = image.copy()
    result = srgb_encode(buffer, out=buffer)
    assert result is buffer
    np.testing.assert_array_equal(buffer, expected)
    srgb_decode(buffer, out=buffer)
    np.testing.assert_array_equal(buffer, srgb_decode(expected))


def test_srgb_keeps_float32() -> None:
    image = np.full((2, 2, 3), 0.5, dtype=np.float32)
    assert srgb_encode(image).dtype == np.float32
    assert srgb_decode(image).dtype == np.float32


def test_srgb_is_monotonic() -> None:
    ramp = np.linspace(-0.1, 2.0, 10_001)
    assert np.all(np.diff(srgb_encode(ramp)) > 0)
    assert np.all(np.diff(srgb_decode(ramp)) > 0)


def test_out_shape_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="shape"):
        srgb_encode(np.zeros((2, 2, 3)), out=np.zeros((2, 3)))


# --- EV --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("linear", "ev"),
    [(MIDDLE_GREY, 0.0), (0.36, 1.0), (0.09, -1.0), (0.72, 2.0), (MIDDLE_GREY / 8, -3.0)],
)
def test_ev_known_values(linear: float, ev: float) -> None:
    np.testing.assert_allclose(linear_to_ev(np.array([linear])), [ev], atol=1e-12)


@given(_float32_arrays(2.0**-13, 64.0))
def test_ev_round_trip(image: np.ndarray) -> None:
    restored = ev_to_linear(linear_to_ev(image))
    np.testing.assert_allclose(restored, image, rtol=1e-6)


@given(_float32_arrays(2.0**-13, 64.0))
def test_ev_matches_numpy_log2(image: np.ndarray) -> None:
    expected = np.log2(image.astype(np.float64) / MIDDLE_GREY)
    np.testing.assert_allclose(linear_to_ev(image), expected, atol=1e-5)


def test_ev_clamps_zero_and_negatives_to_the_floor() -> None:
    ev = linear_to_ev(np.array([0.0, -1.0, EV_FLOOR]))
    assert np.all(np.isfinite(ev))
    np.testing.assert_allclose(ev, np.log2(EV_FLOOR / MIDDLE_GREY))


def test_ev_custom_middle_grey() -> None:
    np.testing.assert_allclose(linear_to_ev(np.array([0.5]), middle_grey=0.25), [1.0])
    np.testing.assert_allclose(ev_to_linear(np.array([1.0]), middle_grey=0.25), [0.5])


def test_ev_in_place() -> None:
    buffer = np.array([0.09, 0.18, 0.36], dtype=np.float32)
    assert linear_to_ev(buffer, out=buffer) is buffer
    np.testing.assert_allclose(buffer, [-1.0, 0.0, 1.0], atol=1e-6)
    ev_to_linear(buffer, out=buffer)
    np.testing.assert_allclose(buffer, [0.09, 0.18, 0.36], rtol=1e-6)
