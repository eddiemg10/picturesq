"""The white balance check: two estimators of the light, compared with the as-shot white."""

import json

import numpy as np
import pytest

from picturesq.colour.spaces import D65, REC2020_TO_XYZ
from picturesq.colour.temperature import (
    bradford_matrix,
    kelvin_tint_to_xy,
    mired,
    white_balance_matrix,
    xy_to_kelvin_tint,
    xy_to_xyz,
    xyz_to_xy,
)
from picturesq.config import WhiteBalanceConfig
from picturesq.decode import PhotoInfo
from picturesq.normalise import (
    WhiteEstimate,
    check_white_balance,
    estimate_white_brightest,
    estimate_white_grey,
    white_balance_flags,
)
from picturesq.normalise.flags import WB_DISAGREEMENT
from picturesq.normalise.white_balance_check import estimates_disagree

AS_SHOT = kelvin_tint_to_xy(5000.0, 0.0)
CLIP = 1.0


def _info(xy: tuple[float, float] | None = AS_SHOT) -> PhotoInfo:
    kelvin, tint = (None, None) if xy is None else xy_to_kelvin_tint(xy)
    return PhotoInfo(
        as_shot_xy=xy,
        as_shot_kelvin=kelvin,
        as_shot_tint=tint,
        baseline_exposure_ev=0.0,
        clip_level=CLIP,
    )


def _decoded(scene: np.ndarray, light: tuple[float, float]) -> np.ndarray:
    """``scene`` (linear Rec.2020 under D65) lit by ``light`` and decoded for ``AS_SHOT``.

    A neutral surface under ``light`` has XYZ ``xy_to_xyz(light)``; the decode adapts from
    the as-shot white to D65 (Bradford), so it lands at ``bradford(AS_SHOT, D65)`` of that.
    Re-balancing the scene from D65 to that white puts every neutral there.
    """
    lands_at = xyz_to_xy(bradford_matrix(AS_SHOT, D65) @ xy_to_xyz(light))
    matrix = white_balance_matrix(D65, lands_at).astype(np.float32)
    return np.ascontiguousarray(scene @ matrix.T)


def _greys(shape: tuple[int, int], low: float, high: float, seed: int = 0) -> np.ndarray:
    """Neutral pixels with luminance spread log-uniformly between ``low`` and ``high``."""
    rng = np.random.default_rng(seed)
    levels = np.exp(rng.uniform(np.log(low), np.log(high), shape)).astype(np.float32)
    return np.repeat(levels[..., None], 3, axis=-1)


def _scene_mired(xy: tuple[float, float] | None) -> float:
    """Mired of an estimate in the decoded image's terms, mapped back to the scene."""
    assert xy is not None
    scene = xyz_to_xy(bradford_matrix(D65, AS_SHOT) @ xy_to_xyz(xy))
    return mired(xy_to_kelvin_tint(scene)[0])


@pytest.mark.parametrize(("kelvin", "tint"), [(5000.0, 0.0), (4000.0, 5.0), (6500.0, -8.0)])
def test_both_estimators_find_the_light_of_a_neutral_scene(kelvin: float, tint: float) -> None:
    light = kelvin_tint_to_xy(kelvin, tint)
    image = _decoded(_greys((120, 160), 0.01, 0.8), light)
    for estimate in (estimate_white_brightest, estimate_white_grey):
        assert _scene_mired(estimate(image, CLIP)) == pytest.approx(mired(kelvin), abs=5.0)


def test_a_known_shift_is_measured_in_mired() -> None:
    light = kelvin_tint_to_xy(4000.0, 5.0)
    check = check_white_balance(
        _decoded(_greys((120, 160), 0.01, 0.8), light), _info(), WhiteBalanceConfig()
    )
    expected = mired(4000.0) - mired(5000.0)  # 50 mired warmer
    assert check.brightest is not None
    assert check.grey is not None
    for estimate in (check.brightest, check.grey):
        assert estimate.delta_mired == pytest.approx(expected, abs=5.0)
        assert estimate.kelvin == pytest.approx(4000.0, rel=0.03)
        assert estimate.delta_tint == pytest.approx(5.0, abs=1.0)
    assert check.disagrees
    assert check.reason is None


def test_no_disagreement_on_an_unchanged_neutral_scene() -> None:
    check = check_white_balance(_greys((120, 160), 0.01, 0.8), _info(), WhiteBalanceConfig())
    assert check.brightest is not None
    assert check.grey is not None
    assert abs(check.brightest.delta_mired) < 1.0
    assert abs(check.grey.delta_mired) < 1.0
    assert not check.disagrees
    assert white_balance_flags(check, WhiteBalanceConfig(flag_disagreement=True)) == []


def test_a_scene_dominated_by_one_colour_still_finds_its_grey_patch() -> None:
    # 80 % saturated green foliage, 20 % brighter grey wall, under 4000 K light.
    scene = _greys((100, 160), 0.02, 0.15, seed=1) * np.array([0.3, 1.0, 0.2], np.float32)
    scene[:, :32] = _greys((100, 32), 0.2, 0.8, seed=2)
    light = kelvin_tint_to_xy(4000.0, 0.0)
    image = _decoded(scene, light)
    for estimate in (estimate_white_brightest, estimate_white_grey):
        assert _scene_mired(estimate(image, CLIP)) == pytest.approx(mired(4000.0), abs=5.0)
    # Plain grey world (the mean of every pixel) is fooled by the green.
    plain = image.reshape(-1, 3).mean(axis=0, dtype=np.float64)
    plain_xy = xyz_to_xy(REC2020_TO_XYZ @ plain)
    assert abs(_scene_mired(plain_xy) - mired(4000.0)) > 20.0


def test_no_flag_when_only_one_estimator_disagrees() -> None:
    # A neutral room under the as-shot light, with a bright orange lamp shade as its
    # brightest thing: the brightest estimator is fooled, the grey one isn't.
    scene = _greys((100, 160), 0.01, 0.3)
    scene[:10, :40] = np.array([0.9, 0.55, 0.25], np.float32)
    check = check_white_balance(scene, _info(), WhiteBalanceConfig())
    assert check.brightest is not None
    assert check.grey is not None
    assert check.brightest.delta_mired > 30.0
    assert abs(check.grey.delta_mired) < 5.0
    assert not check.disagrees
    assert white_balance_flags(check, WhiteBalanceConfig(flag_disagreement=True)) == []


def _estimate(delta_mired: float) -> WhiteEstimate:
    return WhiteEstimate(kelvin=5000.0, tint=0.0, delta_mired=delta_mired, delta_tint=0.0)


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        (35.0, 40.0, True),
        (-35.0, -31.0, True),
        (30.0, 30.0, True),  # the limit itself counts
        (35.0, 25.0, False),  # only one
        (35.0, -40.0, False),  # opposite directions
        (0.0, 0.0, False),
    ],
)
def test_disagreement_needs_both_estimates_the_same_way(
    first: float, second: float, expected: bool
) -> None:
    assert estimates_disagree(_estimate(first), _estimate(second), 30.0) is expected


def test_clipped_pixels_are_ignored() -> None:
    scene = _greys((100, 160), 0.01, 0.5)
    # A clipped, colourful highlight: the brightest thing, but not the light's colour.
    scene[:20, :40] = np.array([CLIP, CLIP, 0.6], np.float32)
    xy = estimate_white_brightest(scene, CLIP)
    assert _scene_mired(xy) == pytest.approx(mired(5000.0), abs=1.0)
    # After +1 EV of exposure the clip level doubles too.
    scene *= 2.0
    check = check_white_balance(scene, _info(), WhiteBalanceConfig(), exposure_ev=1.0)
    assert check.brightest is not None
    assert abs(check.brightest.delta_mired) < 1.0


def test_too_few_usable_pixels() -> None:
    clipped = np.full((50, 50, 3), CLIP, np.float32)
    assert estimate_white_brightest(clipped, CLIP) is None
    assert estimate_white_grey(clipped, CLIP) is None
    check = check_white_balance(clipped, _info(), WhiteBalanceConfig())
    assert (check.disagrees, check.reason) == (False, "too few usable pixels")


def test_grey_needs_nearly_neutral_pixels() -> None:
    colourful = _greys((100, 160), 0.01, 0.5) * np.array([1.0, 0.2, 0.1], np.float32)
    assert estimate_white_grey(colourful, CLIP) is None
    assert estimate_white_brightest(colourful, CLIP) is not None


def test_missing_as_shot_white() -> None:
    check = check_white_balance(_greys((50, 50), 0.01, 0.8), _info(None), WhiteBalanceConfig())
    assert not check.disagrees
    assert check.reason == "no as-shot white"
    assert (check.as_shot_kelvin, check.brightest, check.grey) == (None, None, None)
    assert white_balance_flags(check, WhiteBalanceConfig(flag_disagreement=True)) == []


def test_to_dict_is_json_ready_and_rounded() -> None:
    light = kelvin_tint_to_xy(4000.0, 5.0)
    check = check_white_balance(
        _decoded(_greys((120, 160), 0.01, 0.8), light), _info(), WhiteBalanceConfig()
    )
    data = json.loads(json.dumps(check.to_dict()))
    assert set(data) == {
        "as_shot_kelvin",
        "as_shot_tint",
        "brightest",
        "grey",
        "disagrees",
        "reason",
    }
    assert set(data["grey"]) == {"kelvin", "tint", "delta_mired", "delta_tint"}
    assert data["brightest"]["delta_mired"] == round(data["brightest"]["delta_mired"], 1)
    assert data["disagrees"] is True


def test_wb_disagreement_flag_is_off_by_default() -> None:
    light = kelvin_tint_to_xy(4000.0, 0.0)
    config = WhiteBalanceConfig()
    assert config.flag_disagreement is False
    check = check_white_balance(_decoded(_greys((120, 160), 0.01, 0.8), light), _info(), config)
    # The check still runs and still disagrees; only the flag is off.
    assert check.disagrees
    assert check.grey is not None
    assert check.grey.delta_mired == pytest.approx(50.0, abs=5.0)
    assert white_balance_flags(check, config) == []


def test_wb_disagreement_flag() -> None:
    light = kelvin_tint_to_xy(4000.0, 0.0)
    config = WhiteBalanceConfig(flag_disagreement=True)
    check = check_white_balance(_decoded(_greys((120, 160), 0.01, 0.8), light), _info(), config)
    (flag,) = white_balance_flags(check, config)
    assert flag.name == WB_DISAGREEMENT
    assert "warmer" in flag.message
    assert "5000 K" in flag.message
    assert flag.details["limit_mired"] == 30.0
    assert flag.details["grey_delta_mired"] == pytest.approx(50.0, abs=5.0)
    json.dumps(flag.to_dict())
    # A wider limit: no flag.
    wide = WhiteBalanceConfig(flag_disagreement=True, flag_disagreement_mired=60.0)
    assert (
        white_balance_flags(
            check_white_balance(_decoded(_greys((120, 160), 0.01, 0.8), light), _info(), wide), wide
        )
        == []
    )


def test_cooler_light_is_flagged_as_cooler() -> None:
    light = kelvin_tint_to_xy(7500.0, 0.0)  # 67 mired cooler than 5000 K
    config = WhiteBalanceConfig(flag_disagreement=True)
    check = check_white_balance(_decoded(_greys((120, 160), 0.01, 0.8), light), _info(), config)
    (flag,) = white_balance_flags(check, config)
    assert "cooler" in flag.message
