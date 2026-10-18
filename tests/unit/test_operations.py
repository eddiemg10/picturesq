"""Grade operations: intensity scaling, neutrality and the first four operations."""

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from picturesq import parallel
from picturesq.colour.oklab import rec2020_to_oklab
from picturesq.colour.spaces import D65, REC2020_TO_XYZ
from picturesq.colour.temperature import white_balance_matrix
from picturesq.config.operations import (
    MAX_INTENSITY,
    OPERATION_TYPES,
    ContrastOperation,
    ExposureOperation,
    FadeOperation,
    HslOperation,
    HueBand,
    Operation,
    SaturationOperation,
    SplitToneOperation,
    ToneCurveOperation,
    ToneTint,
    VibranceOperation,
    WhiteBalanceOperation,
)
from picturesq.grade.operations import (
    _FUNCTIONS,
    apply_operation,
    apply_operations,
    white_balance_operation_matrix,
)

LOOK_VALUES: list[Operation] = [
    ExposureOperation(ev=0.7),
    WhiteBalanceOperation(warmth=25.0, tint=-6.0),
    ContrastOperation(amount=0.3, pivot=0.2),
    SaturationOperation(amount=-0.4),
    ToneCurveOperation(points=((-3.0, -3.4), (0.0, 0.0), (2.0, 1.5))),
    FadeOperation(amount=0.06),
    VibranceOperation(amount=0.4),
    HslOperation(blue=HueBand(hue=-10.0, chroma=0.2, lightness=-0.5), orange=HueBand(chroma=-0.2)),
    SplitToneOperation(
        shadows=ToneTint(hue=220.0, amount=0.3), highlights=ToneTint(hue=60.0, amount=0.2)
    ),
]


def _image(seed: int = 0, shape: tuple[int, int] = (17, 23)) -> np.ndarray:
    rng = np.random.default_rng(seed)
    # Scene-linear: mostly 0-1, some highlights, a few out-of-gamut (negative) channels.
    image = rng.lognormal(np.log(0.18), 1.5, (*shape, 3)).astype(np.float32)
    image[0, :3] = [-0.01, 0.2, 0.3]
    return image


def _luminance(image: np.ndarray) -> np.ndarray:
    return image @ REC2020_TO_XYZ[1].astype(np.float32)


def test_every_operation_has_a_function() -> None:
    assert set(OPERATION_TYPES) == set(_FUNCTIONS)


@pytest.mark.parametrize("operation_type", OPERATION_TYPES)
def test_defaults_are_neutral(operation_type: type[Operation]) -> None:
    assert operation_type().is_neutral()


@pytest.mark.parametrize("operation", LOOK_VALUES, ids=lambda o: o.op)
def test_scaled_moves_from_neutral_to_value(operation: Operation) -> None:
    assert operation.scaled(0.0).is_neutral()
    assert operation.scaled(1.0) == operation
    half, full = operation.scaled(0.5), operation
    for name, value in full.model_dump().items():
        if isinstance(value, float) and name != "pivot":
            assert getattr(half, name) == pytest.approx(value / 2)


def test_scaled_keeps_unscaled_values() -> None:
    scaled = ContrastOperation(amount=0.3, pivot=0.25).scaled(0.5)
    assert scaled.pivot == 0.25
    assert scaled.amount == pytest.approx(0.15)


def test_scaled_may_pass_the_declared_range() -> None:
    """Up to 150 % intensity, a value can exceed what a look file may declare."""
    scaled = SaturationOperation(amount=-1.0).scaled(MAX_INTENSITY)
    assert scaled.amount == -1.5
    with pytest.raises(ValidationError):
        SaturationOperation(amount=-1.5)


@pytest.mark.parametrize("operation", LOOK_VALUES, ids=lambda o: o.op)
def test_intensity_zero_is_bit_identical(operation: Operation) -> None:
    image = _image()
    before = image.copy()
    assert apply_operation(image, operation, 0.0) is image
    assert np.array_equal(image, before)


@pytest.mark.parametrize("operation_type", OPERATION_TYPES)
def test_neutral_values_are_bit_identical(operation_type: type[Operation]) -> None:
    image = _image()
    before = image.copy()
    apply_operation(image, operation_type(), 1.0)
    assert np.array_equal(image, before)


@pytest.mark.parametrize("operation", LOOK_VALUES, ids=lambda o: o.op)
def test_block_size_and_threads_never_change_the_result(operation: Operation) -> None:
    results = []
    for threads, block in [(1, 1 << 15), (4, 1 << 15), (3, 1 << 16)]:
        image = _image(shape=(300, 250))
        with parallel.using(parallel.Parallelism(threads=threads, block_pixels=block)):
            results.append(apply_operation(image, operation))
    assert all(np.array_equal(results[0], other) for other in results[1:])


@settings(max_examples=40, deadline=None)
@given(
    seed=st.integers(0, 1000),
    index=st.integers(0, len(LOOK_VALUES) - 1),
    intensity=st.floats(0.0, MAX_INTENSITY),
)
def test_operations_keep_pixels_finite(seed: int, index: int, intensity: float) -> None:
    image = apply_operation(_image(seed), LOOK_VALUES[index], intensity)
    assert np.isfinite(image).all()


def test_exposure_one_stop_doubles() -> None:
    image = _image()
    expected = image * 2.0
    apply_operation(image, ExposureOperation(ev=1.0))
    np.testing.assert_array_equal(image, expected)


def test_exposure_intensity_scales_stops() -> None:
    image = _image()
    expected = image * np.float32(2.0**0.5)
    apply_operation(image, ExposureOperation(ev=1.0), 0.5)
    np.testing.assert_allclose(image, expected, rtol=1e-6)


def test_white_balance_matrix_is_chromatic_adaptation() -> None:
    """Warmth re-balances from a light that many mired bluer than D65, to D65."""
    operation = WhiteBalanceOperation(warmth=20.0, tint=0.0)
    matrix = white_balance_operation_matrix(operation)
    grey = np.full((1, 1, 3), 0.18, dtype=np.float32)
    apply_operation(grey, operation)
    np.testing.assert_allclose(grey[0, 0], matrix @ np.full(3, 0.18), rtol=1e-5)


def test_white_balance_at_neutral_values_is_identity_matrix() -> None:
    matrix = white_balance_operation_matrix(WhiteBalanceOperation())
    np.testing.assert_allclose(matrix, white_balance_matrix(D65, D65), atol=1e-4)


@pytest.mark.parametrize("warmth", [15.0, 60.0])
def test_positive_warmth_is_warmer_and_about_keeps_luminance(warmth: float) -> None:
    grey = np.full((1, 1, 3), 0.18, dtype=np.float32)
    apply_operation(grey, WhiteBalanceOperation(warmth=warmth))
    red, _, blue = grey[0, 0]
    assert red > 0.18 > blue
    # Adaptation keeps the source white's luminance, not this grey's: about 1 % at 60 mired
    # (0.01 EV), as in raw converters' temperature sliders.
    assert _luminance(grey)[0, 0] == pytest.approx(0.18, rel=0.015)


def test_negative_warmth_is_cooler() -> None:
    grey = np.full((1, 1, 3), 0.18, dtype=np.float32)
    apply_operation(grey, WhiteBalanceOperation(warmth=-30.0))
    assert grey[0, 0, 2] > 0.18 > grey[0, 0, 0]


def test_positive_tint_is_magenta() -> None:
    grey = np.full((1, 1, 3), 0.18, dtype=np.float32)
    apply_operation(grey, WhiteBalanceOperation(tint=15.0))
    red, green, blue = grey[0, 0]
    assert green < red and green < blue


@pytest.mark.parametrize("intensity", [1.0, MAX_INTENSITY])
def test_white_balance_extremes_stay_on_the_locus_table(intensity: float) -> None:
    for warmth in (-100.0, 100.0):
        image = apply_operation(_image(), WhiteBalanceOperation(warmth=warmth), intensity)
        assert np.isfinite(image).all()


def test_contrast_keeps_the_pivot_and_scales_stops() -> None:
    pivot = 0.2
    levels = pivot * 2.0 ** np.array([-3.0, -1.0, 0.0, 1.0, 2.0])
    image = np.repeat(levels[:, None], 3, axis=1).astype(np.float32)[None]
    apply_operation(image, ContrastOperation(amount=0.5, pivot=pivot))
    stops = np.log2(_luminance(image)[0] / pivot)
    np.testing.assert_allclose(stops, [-4.5, -1.5, 0.0, 1.5, 3.0], atol=1e-4)


def test_contrast_keeps_colour_ratios() -> None:
    image = np.array([[[0.3, 0.1, 0.05], [0.02, 0.04, 0.09]]], dtype=np.float32)
    ratios = image / image[..., 1:2]
    apply_operation(image, ContrastOperation(amount=0.4))
    np.testing.assert_allclose(image / image[..., 1:2], ratios, rtol=1e-5)


def test_contrast_is_monotone_at_the_lowest_slope() -> None:
    levels = np.geomspace(1e-4, 16.0, 50)
    image = np.repeat(levels[:, None], 3, axis=1).astype(np.float32)[None]
    apply_operation(image, ContrastOperation(amount=-0.9), MAX_INTENSITY)
    assert (np.diff(_luminance(image)[0]) > 0).all()


def test_saturation_scales_chroma_keeping_lightness_and_hue() -> None:
    image = _image()[1:]  # in-gamut pixels only (cube roots of negatives are fine, but noisier)
    before = rec2020_to_oklab(image.copy())
    apply_operation(image, SaturationOperation(amount=0.5))
    after = rec2020_to_oklab(image.copy())
    np.testing.assert_allclose(after[..., 0], before[..., 0], atol=1e-4)
    np.testing.assert_allclose(after[..., 1:], 1.5 * before[..., 1:], atol=1e-4)


def test_saturation_minus_one_is_grey_and_never_inverts() -> None:
    for intensity in (1.0, MAX_INTENSITY):
        image = _image()
        apply_operation(image, SaturationOperation(amount=-1.0), intensity)
        lab = rec2020_to_oklab(image.copy())
        np.testing.assert_allclose(lab[..., 1:], 0.0, atol=1e-4)


def test_apply_operations_runs_one_space_in_order() -> None:
    image = np.full((1, 1, 3), 0.18, dtype=np.float32)
    operations = [ExposureOperation(ev=1.0), ContrastOperation(amount=1.0)]
    apply_operations(image, operations, 1.0, "scene")
    # Exposure first: 0.36 is one stop above the pivot, contrast doubles it to two stops.
    np.testing.assert_allclose(image, 0.72, rtol=1e-5)
    untouched = np.full((1, 1, 3), 0.18, dtype=np.float32)
    apply_operations(untouched, operations, 1.0, "display")
    np.testing.assert_array_equal(untouched, np.float32(0.18))
