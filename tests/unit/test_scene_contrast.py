import numpy as np
import pytest
from pydantic import ValidationError

from picturesq.colour.spaces import REC2020_TO_XYZ
from picturesq.colour.transfer import MIDDLE_GREY
from picturesq.config import NormaliseOverrides, ProjectConfig, SceneContrastConfig
from picturesq.normalise import (
    apply_scene_contrast,
    normalise,
    normalise_with_decision,
    scene_contrast,
    scene_contrast_decision,
)
from picturesq.photo import PhotoContext

Y = REC2020_TO_XYZ[1]


def _ev(image: np.ndarray) -> np.ndarray:
    return np.log2((image.astype(np.float64) @ Y) / MIDDLE_GREY)


def _grey_ramp(evs: np.ndarray) -> np.ndarray:
    """One row of greys at the given EVs (relative to mid grey)."""
    values = (MIDDLE_GREY * 2.0**evs).astype(np.float32)
    return np.repeat(values[None, :, None], 3, axis=2)


def _flat_scene(range_ev: float, seed: int = 0) -> np.ndarray:
    """A coloured scene whose luminance is uniform in EV over ``range_ev`` (p5-p95 = 0.9x)."""
    rng = np.random.default_rng(seed)
    evs = rng.uniform(-range_ev / 2, range_ev / 2, size=(120, 160))
    tint = rng.uniform(0.6, 1.4, size=(120, 160, 3))
    tint /= (tint @ Y)[..., None]
    return (MIDDLE_GREY * 2.0 ** evs[..., None] * tint).astype(np.float32)


# --- the per-pixel curve ----------------------------------------------------------------------


EVS = np.linspace(-12.0, 8.0, 401)


def test_pivot_stays_put() -> None:
    image = _grey_ramp(np.array([-1.0, 0.5, 2.0]))
    out = apply_scene_contrast(image.copy(), 0.4, pivot_ev=0.5, soft_limit_ev=3.0)
    assert _ev(out)[0, 1] == pytest.approx(0.5, abs=1e-5)


def test_curve_is_monotonic_and_bounded() -> None:
    contrast, limit = 0.5, 3.0
    image = _grey_ramp(EVS)
    out = apply_scene_contrast(image.copy(), contrast, pivot_ev=1.0, soft_limit_ev=limit)
    after = _ev(out)[0]
    assert np.all(np.diff(after) > 0)  # order of tones is kept
    added = after - EVS
    assert np.all(np.abs(added) <= contrast * limit + 1e-4)
    assert added[0] == pytest.approx(-contrast * limit, abs=0.01)  # levels off far away
    assert np.all(added[EVS < 1.0] < 0) and np.all(added[EVS > 1.0] > 0)


def test_slope_at_pivot_is_one_plus_contrast() -> None:
    image = _grey_ramp(np.array([-0.01, 0.01]))
    out = apply_scene_contrast(image, 0.25, pivot_ev=0.0, soft_limit_ev=3.0)
    slope = np.diff(_ev(out)[0])[0] / 0.02
    assert slope == pytest.approx(1.25, rel=1e-3)


def test_greys_stay_grey_and_colour_ratios_are_kept() -> None:
    image = _flat_scene(3.0)
    before = image.copy()
    apply_scene_contrast(image, 0.5, pivot_ev=0.0, soft_limit_ev=3.0)
    ratio = image / before
    assert np.allclose(ratio[..., 0], ratio[..., 1], rtol=1e-5)
    assert np.allclose(ratio[..., 1], ratio[..., 2], rtol=1e-5)
    greys = _grey_ramp(EVS)
    apply_scene_contrast(greys, 0.5, pivot_ev=0.0, soft_limit_ev=3.0)
    assert np.array_equal(greys[..., 0], greys[..., 1])
    assert np.array_equal(greys[..., 1], greys[..., 2])


def test_zero_contrast_leaves_image_untouched_and_float32_in_place() -> None:
    image = _flat_scene(2.0)
    before = image.copy()
    assert apply_scene_contrast(image, 0.0, 0.0, 3.0) is image
    assert np.array_equal(image, before)
    assert apply_scene_contrast(image, 0.3, 0.0, 3.0) is image
    assert image.dtype == np.float32


def test_black_and_negative_pixels_stay_finite() -> None:
    image = np.array([[[0.0, 0.0, 0.0], [-0.01, 0.02, 0.01]]], dtype=np.float32)
    apply_scene_contrast(image, 0.5, 0.0, 3.0)
    assert np.all(np.isfinite(image))


# --- the extra contrast per scene -------------------------------------------------------------


def test_contrast_rule() -> None:
    config = SceneContrastConfig(target_range_ev=4.5, max_contrast=0.5)
    assert scene_contrast(4.5, config, 1.0) == 0.0  # at the target range: nothing
    assert scene_contrast(8.0, config, 1.0) == 0.0  # wider: nothing
    assert scene_contrast(3.6, config, 1.0) == pytest.approx(0.25)  # 4.5 / 3.6 - 1
    assert scene_contrast(3.6, config, 0.5) == pytest.approx(0.125)  # gentle
    assert scene_contrast(1.0, config, 1.0) == pytest.approx(0.5)  # capped
    assert scene_contrast(0.0, config, 1.0) == pytest.approx(0.5)  # uniform photo
    assert scene_contrast(1.0, config, 0.0) == 0.0


def test_decision_measures_range_and_pivot() -> None:
    evs = np.linspace(-2.0, 2.0, 1000)  # p5 -1.8, p95 1.8, p75 1.0
    config = SceneContrastConfig()
    decision = scene_contrast_decision(_grey_ramp(evs), config, config.amount)
    assert decision.range_ev == pytest.approx(3.6, abs=0.01)
    assert decision.pivot_ev == pytest.approx(1.0, abs=0.01)
    assert decision.contrast == pytest.approx(0.5 * 0.25, abs=0.002)


# --- config -----------------------------------------------------------------------------------


def test_defaults() -> None:
    config = ProjectConfig().normalise.scene_contrast
    assert config.enabled is False
    assert config.amount == 0.5
    assert config.target_range_ev == 4.5
    assert config.max_contrast == 0.5
    assert config.pivot_percentile == 75.0
    assert config.soft_limit_ev == 3.0
    assert NormaliseOverrides().scene_contrast is None


@pytest.mark.parametrize(
    "fields",
    [
        {"amount": -0.1},
        {"amount": 2.5},
        {"target_range_ev": 0.0},
        {"max_contrast": -1.0},
        {"pivot_percentile": 101.0},
        {"soft_limit_ev": 0.0},
        {"strength": 1.0},
    ],
)
def test_invalid_config_is_rejected(fields: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        SceneContrastConfig.model_validate(fields)


@pytest.mark.parametrize("value", [-0.5, 3.0])
def test_invalid_override_is_rejected(value: float) -> None:
    with pytest.raises(ValidationError):
        NormaliseOverrides(scene_contrast=value)


# --- in normalise -----------------------------------------------------------------------------


def _config(scene_contrast: dict[str, object], override: float | None = None) -> ProjectConfig:
    photos = {} if override is None else {"a.dng": {"normalise": {"scene_contrast": override}}}
    return ProjectConfig.model_validate(
        {"normalise": {"scene_contrast": scene_contrast}, "photos": photos}
    )


A = PhotoContext(name="a.dng")


def test_off_by_default_is_bit_identical() -> None:
    image = _flat_scene(2.0)
    reference = image.copy()
    off = ProjectConfig.model_validate(
        {"normalise": {"scene_contrast": {"enabled": False, "amount": 2.0}}}
    )
    normalise(image, ProjectConfig(), A)
    normalise(reference, off, A)
    assert np.array_equal(image, reference)
    decision = normalise_with_decision(_flat_scene(2.0), ProjectConfig(), A)
    assert decision is not None
    assert decision.scene_contrast is None


def test_enabled_adds_contrast_to_a_flat_scene_only() -> None:
    config = _config({"enabled": True})
    flat = normalise_with_decision(_flat_scene(2.0), config, A)
    assert flat is not None and flat.scene_contrast is not None
    assert flat.scene_contrast.contrast == pytest.approx(0.25)  # 0.5 x max 0.5
    image = _flat_scene(8.0)
    plain = image.copy()
    wide = normalise_with_decision(image, config, A)
    normalise(plain, ProjectConfig(), A)
    assert wide is not None and wide.scene_contrast is not None
    assert wide.scene_contrast.contrast == 0.0
    assert np.array_equal(image, plain)


def test_flat_scene_spreads_out() -> None:
    image = _flat_scene(2.0)
    plain = image.copy()
    normalise(image, _config({"enabled": True, "amount": 1.0}), A)
    normalise(plain, ProjectConfig(), A)
    spread = np.subtract(*np.percentile(_ev(image), [95, 5]))
    plain_spread = np.subtract(*np.percentile(_ev(plain), [95, 5]))
    assert spread > plain_spread * 1.3


def test_override_replaces_amount_even_when_off() -> None:
    on = normalise_with_decision(_flat_scene(2.0), _config({"enabled": False}, override=1.0), A)
    assert on is not None and on.scene_contrast is not None
    assert on.scene_contrast.contrast == pytest.approx(0.5)  # 1.0 x max 0.5
    other = normalise_with_decision(
        _flat_scene(2.0), _config({"enabled": False}, 1.0), PhotoContext(name="b.dng")
    )
    assert other is not None and other.scene_contrast is None


def test_override_zero_turns_it_off() -> None:
    image = _flat_scene(2.0)
    plain = image.copy()
    decision = normalise_with_decision(image, _config({"enabled": True}, override=0.0), A)
    normalise(plain, ProjectConfig(), A)
    assert decision is not None and decision.scene_contrast is None
    assert np.array_equal(image, plain)
