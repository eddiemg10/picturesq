"""AgX-style display transform (#17)."""

import os
from pathlib import Path

import colour
import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from picturesq.colour.agx import (
    AgxCurve,
    _lookup,  # pyright: ignore[reportPrivateUsage]
    agx,
    inset_space,
    sigmoid,
)
from picturesq.colour.spaces import (
    REC709,
    REC709_TO_REC2020,
    REC709_TO_XYZ,
    apply_matrix,
    rgb_to_rgb_matrix,
)
from picturesq.colour.transfer import (
    MIDDLE_GREY,
    SRGB_GREY_ENCODED,
    SRGB_GREY_SLOPE_PER_EV,
    srgb_decode,
)
from picturesq.config import DisplayTransformConfig
from picturesq.parallel import DEFAULT_BLOCK_PIXELS

GOLDEN = Path(__file__).parents[1] / "golden" / "agx_ramp.npy"
DEFAULT = AgxCurve.from_config(DisplayTransformConfig())


def _grey(values: np.ndarray) -> np.ndarray:
    return np.repeat(values.astype(np.float32)[None, :, None], 3, axis=2)


def _ev_ramp(start: float = -12.0, stop: float = 9.0, steps: int = 400) -> np.ndarray:
    return MIDDLE_GREY * 2.0 ** np.linspace(start, stop, steps)


def _hue_ramps() -> tuple[np.ndarray, np.ndarray]:
    """Saturated Rec.709 colours every 30° of hue, each from -3 to +7 EV (scene, Rec.2020).

    Returns (scene image of shape hues x exposures x 3, base Rec.709 colours).
    """
    hues = np.arange(0, 360, 30) / 360.0
    base = np.array([colour.HSV_to_RGB([h, 0.85, 1.0]) for h in hues]) * 0.36
    gains = 2.0 ** np.arange(-3.0, 7.01, 0.5)
    scene = base[:, None, :] * gains[None, :, None]
    return apply_matrix(scene, REC709_TO_REC2020).astype(np.float32), base


def _oklab(rgb709: np.ndarray) -> np.ndarray:
    return colour.XYZ_to_Oklab(apply_matrix(rgb709.astype(np.float64), REC709_TO_XYZ))


# --- the curve -----------------------------------------------------------------------------


def test_sigmoid_ends_and_pivot() -> None:
    x = np.array([0.0, DEFAULT.pivot_x, 1.0])
    np.testing.assert_allclose(sigmoid(x, DEFAULT), [0.0, SRGB_GREY_ENCODED, 1.0], atol=1e-9)


def test_sigmoid_slope_at_pivot() -> None:
    h = 1e-6
    x = np.array([DEFAULT.pivot_x - h, DEFAULT.pivot_x + h])
    y = sigmoid(x, DEFAULT)
    np.testing.assert_allclose((y[1] - y[0]) / (2 * h), DEFAULT.slope, rtol=1e-4)


@given(
    contrast=st.floats(1.0, 2.5),
    toe=st.floats(0.5, 6.0),
    shoulder=st.floats(0.5, 6.0),
    max_ev=st.floats(4.0, 10.0),
)
def test_sigmoid_monotonic(contrast: float, toe: float, shoulder: float, max_ev: float) -> None:
    config = DisplayTransformConfig(contrast=contrast, toe=toe, shoulder=shoulder, max_ev=max_ev)
    curve = AgxCurve.from_config(config)
    y = sigmoid(np.linspace(0.0, 1.0, 2001), curve)
    assert np.all(np.diff(y) >= 0.0)
    assert y[0] == pytest.approx(0.0, abs=1e-9)
    assert y[-1] == pytest.approx(1.0, abs=1e-9)


# --- the whole transform -------------------------------------------------------------------


def test_mid_grey_maps_to_mid_grey() -> None:
    result = agx(_grey(np.array([MIDDLE_GREY])), DEFAULT)
    np.testing.assert_allclose(result, MIDDLE_GREY, atol=1e-5)


def test_greys_stay_neutral_and_monotonic() -> None:
    result = agx(_grey(_ev_ramp()), DEFAULT)[0]
    np.testing.assert_allclose(result[:, 0], result[:, 1], atol=1e-5)
    np.testing.assert_allclose(result[:, 1], result[:, 2], atol=1e-5)
    assert np.all(np.diff(result[:, 0]) >= -1e-6)


def test_black_and_white_points() -> None:
    config = DisplayTransformConfig()
    values = MIDDLE_GREY * 2.0 ** np.array([config.min_ev - 1, config.max_ev, config.max_ev + 3])
    result = agx(_grey(values), DEFAULT)[0, :, 0]
    np.testing.assert_allclose(result, [0.0, 1.0, 1.0], atol=1e-5)


def test_highlights_roll_off_instead_of_clipping() -> None:
    # The v0 transform clipped everything above scene 1.0; AgX keeps 1, 2, 4 and 8 apart.
    result = agx(_grey(np.array([1.0, 2.0, 4.0, 8.0])), DEFAULT)[0, :, 0]
    assert np.all(np.diff(result) > 0.01)
    assert result[-1] < 1.0


def test_negative_and_zero_input() -> None:
    image = np.array([[[0.0, 0.0, 0.0], [-0.5, 0.2, 0.1], [-1.0, -1.0, -1.0]]], dtype=np.float32)
    result = agx(image, DEFAULT)
    assert np.all(np.isfinite(result))
    assert result.min() >= 0.0
    np.testing.assert_allclose(result[0, 0], 0.0, atol=1e-6)


def test_output_range_dtype_shape() -> None:
    rng = np.random.default_rng(0)
    image = (rng.random((8, 6, 3)) * 50.0 - 1.0).astype(np.float32)
    result = agx(image, DEFAULT)
    assert result.dtype == np.float32
    assert result.shape == image.shape
    assert result.min() >= 0.0
    assert result.max() <= 1.0


def test_brightening_never_darkens_a_channel_sum() -> None:
    scene, _ = _hue_ramps()
    luma = agx(scene, DEFAULT).sum(axis=-1)
    assert np.all(np.diff(luma, axis=1) >= -1e-5)


def test_no_hue_flips_on_saturated_ramps() -> None:
    """A saturated colour brightening toward white may drift in hue, but never flips.

    Measured in Oklab hue. Defaults drift ≤ ~18° (see DisplayTransformConfig); a flip
    (e.g. orange turning pink, blue turning cyan) would be tens of degrees more.
    """
    scene, base = _hue_ramps()
    display = _oklab(agx(scene, DEFAULT))
    reference = _oklab(base)
    hue = np.degrees(np.arctan2(display[..., 2], display[..., 1]))
    ref_hue = np.degrees(np.arctan2(reference[:, 2], reference[:, 1]))
    chroma = np.hypot(display[..., 1], display[..., 2])
    drift = (hue - ref_hue[:, None] + 180.0) % 360.0 - 180.0
    drift = np.where(chroma > 0.03, drift, 0.0)  # near-white or near-black: hue is undefined
    assert np.abs(drift).max() < 30.0


def test_bright_saturated_colours_go_to_white() -> None:
    scene, _ = _hue_ramps()
    brightest = agx(scene * np.float32(64.0), DEFAULT)[:, -1]
    np.testing.assert_allclose(brightest, 1.0, atol=1e-3)


def test_out_parameter() -> None:
    rng = np.random.default_rng(1)
    image = (rng.random((4, 5, 3)) * 4.0).astype(np.float32)
    expected = agx(image.copy(), DEFAULT)
    out = np.empty_like(image)
    assert agx(image, DEFAULT, out=out) is out
    np.testing.assert_array_equal(out, expected)
    assert agx(image, DEFAULT, out=image) is image
    np.testing.assert_array_equal(image, expected)


def test_golden_ramp() -> None:
    """Regression: grey and hue ramps through the default transform.

    Set PICTURESQ_UPDATE_GOLDENS=1 to rewrite it after a deliberate change.
    """
    scene, _ = _hue_ramps()
    image = np.concatenate([scene, _grey(_ev_ramp(-11.0, 8.0, scene.shape[1]))], axis=0)
    result = agx(image, DEFAULT)
    if os.environ.get("PICTURESQ_UPDATE_GOLDENS") == "1":
        np.save(GOLDEN, result)
    np.testing.assert_allclose(result, np.load(GOLDEN), atol=2e-5)


# --- matrices and config --------------------------------------------------------------------


def test_inset_space_moves_primaries_toward_white() -> None:
    inset = inset_space(REC709, (0.0, 0.5, 1.0))
    assert inset.red == pytest.approx(REC709.red)
    assert inset.green == pytest.approx(
        ((REC709.green[0] + REC709.white[0]) / 2, (REC709.green[1] + REC709.white[1]) / 2)
    )
    assert inset.blue == pytest.approx(REC709.white)


def test_inset_matrix_desaturates_and_keeps_white() -> None:
    matrix = rgb_to_rgb_matrix(inset_space(REC709, (0.25, 0.25, 0.25)), REC709)
    np.testing.assert_allclose(matrix @ np.ones(3), 1.0, atol=1e-12)
    assert np.all(matrix > 0.0)  # every channel picks up some of the others


def test_contrast_is_relative_to_srgb() -> None:
    config = DisplayTransformConfig(contrast=1.0)
    curve = AgxCurve.from_config(config)
    expected = SRGB_GREY_SLOPE_PER_EV * (config.max_ev - config.min_ev)
    assert curve.slope == pytest.approx(expected)


@pytest.mark.parametrize(
    "values",
    [
        {"contrast": 0.3},  # too flat to reach white by max_ev
        {"max_ev": 0.0},
        {"min_ev": 0.0},
        {"inset": (0.2, 0.2, 1.0)},
        {"outset": (-0.1, 0.0, 0.0)},
    ],
)
def test_invalid_config(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        DisplayTransformConfig.model_validate(values)


def test_table_matches_exact_curve() -> None:
    x = np.linspace(0.0, 1.0, 100_003)
    exact = srgb_decode(sigmoid(x, DEFAULT))
    looked_up = x.astype(np.float32)
    _lookup(looked_up, DEFAULT)
    assert np.abs(looked_up - exact).max() < 2e-6


def test_blocks_match_whole_image() -> None:
    rng = np.random.default_rng(2)
    image = (rng.random((3, DEFAULT_BLOCK_PIXELS // 2 + 7, 3)) * 8.0).astype(np.float32)
    strided = np.asfortranarray(image)  # not C-contiguous: processed in one go
    # The two memory layouts round float32 sums differently on some platforms (Windows
    # numpy: up to 1.3e-6); 1e-5 is still ~400x below one 8-bit step.
    np.testing.assert_allclose(agx(image, DEFAULT), agx(strided, DEFAULT), atol=1e-5)


def _chroma(display: np.ndarray) -> np.ndarray:
    lab = _oklab(display)
    return np.hypot(lab[..., 1], lab[..., 2])


def test_chroma_preservation_keeps_bright_colours_colourful() -> None:
    """Per-channel AgX washes a bright sky blue out; the blend keeps more of its chroma."""
    sky = (apply_matrix(np.array([[[0.25, 0.45, 0.9]]]), REC709_TO_REC2020) * 8.0).astype(
        np.float32
    )
    plain = DisplayTransformConfig(chroma_preservation=0.0, saturation=1.0)
    kept = DisplayTransformConfig(chroma_preservation=1.0, saturation=1.0)
    washed = _chroma(agx(sky, AgxCurve.from_config(plain)))
    preserved = _chroma(agx(sky, AgxCurve.from_config(kept)))
    assert preserved[0, 0] > 1.5 * washed[0, 0]


@pytest.mark.parametrize("values", [{"chroma_preservation": 1.0}, {"saturation": 2.0}])
def test_greys_untouched_by_chroma_steps(values: dict[str, float]) -> None:
    curve = AgxCurve.from_config(DisplayTransformConfig.model_validate(values))
    grey = agx(_grey(_ev_ramp()), curve)[0]
    reference = agx(
        _grey(_ev_ramp()),
        AgxCurve.from_config(DisplayTransformConfig(chroma_preservation=0.0, saturation=1.0)),
    )[0]
    np.testing.assert_allclose(grey, reference, atol=2e-5)


def test_saturation_fades_toward_white() -> None:
    colours = apply_matrix(np.array([[[0.9, 0.3, 0.2]]]), REC709_TO_REC2020).astype(np.float32)
    dark, bright = colours * np.float32(0.05), colours * np.float32(4.0)
    base = DisplayTransformConfig(saturation=1.0)
    boosted = DisplayTransformConfig(saturation=1.5, saturation_fade=1.0)
    gain_dark = _chroma(agx(dark, AgxCurve.from_config(boosted))) / _chroma(
        agx(dark, AgxCurve.from_config(base))
    )
    gain_bright = _chroma(agx(bright, AgxCurve.from_config(boosted))) / _chroma(
        agx(bright, AgxCurve.from_config(base))
    )
    assert gain_dark[0, 0] > gain_bright[0, 0] > 1.0
