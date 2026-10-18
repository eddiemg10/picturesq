"""Re-balancing a photo from its as-shot white to a white given as kelvin and tint."""

import numpy as np
import pytest

from picturesq.colour.spaces import D65, REC2020_TO_XYZ, XYZ_TO_REC2020
from picturesq.colour.temperature import (
    bradford_matrix,
    kelvin_tint_to_xy,
    white_balance_matrix,
    xy_to_kelvin_tint,
    xy_to_xyz,
    xyz_to_xy,
)
from picturesq.config import NormaliseOverrides
from picturesq.normalise.white_balance import (
    WhiteBalanceOverrideError,
    override_white,
    rebalance_matrix,
    rebalance_white,
)

AS_SHOT = kelvin_tint_to_xy(5200.0, 4.0)


def _decoded_grey(light_xy: tuple[float, float], as_shot_xy: tuple[float, float]) -> np.ndarray:
    """A grey (18 %) lit by ``light_xy``, as a decode balanced for ``as_shot_xy`` gives it."""
    xyz = 0.18 * (bradford_matrix(as_shot_xy, D65) @ xy_to_xyz(light_xy))
    rgb = XYZ_TO_REC2020 @ xyz
    return np.tile(rgb.astype(np.float32), (4, 5, 1))


@pytest.mark.parametrize(("kelvin", "tint"), [(3000.0, 0.0), (6500.0, 0.0), (4300.0, 20.0)])
def test_grey_lit_by_the_target_white_becomes_neutral(kelvin: float, tint: float) -> None:
    light = kelvin_tint_to_xy(kelvin, tint)
    image = _decoded_grey(light, AS_SHOT)
    assert np.ptp(image[0, 0]) > 0.005  # not neutral as decoded
    rebalance_white(image, AS_SHOT, light, out=image)
    np.testing.assert_allclose(image, 0.18, rtol=1e-5)  # neutral, luminance kept


def test_identity_when_the_target_is_the_as_shot_white() -> None:
    np.testing.assert_allclose(rebalance_matrix(AS_SHOT, AS_SHOT), np.eye(3), atol=1e-12)
    image = np.random.default_rng(0).random((6, 7, 3), dtype=np.float32)
    np.testing.assert_allclose(rebalance_white(image, AS_SHOT, AS_SHOT), image, rtol=1e-6)


def test_agrees_with_adapting_the_decoded_grey_to_d65_up_to_a_gain() -> None:
    # The other way to derive it: find where the target-lit grey sits after the decode
    # (xy'), then adapt that to D65. Same matrix, apart from a scalar gain.
    target = kelvin_tint_to_xy(3200.0, -10.0)
    decoded = xyz_to_xy(bradford_matrix(AS_SHOT, D65) @ xy_to_xyz(target))
    other = white_balance_matrix(decoded, D65)
    ours = rebalance_matrix(AS_SHOT, target)
    gain = ours[0, 0] / other[0, 0]
    np.testing.assert_allclose(ours, gain * other, rtol=1e-9)
    assert gain == pytest.approx(1.0, abs=0.05)


def _chromaticity_of_white(image: np.ndarray) -> tuple[float, float]:
    return xyz_to_xy(REC2020_TO_XYZ @ image[0, 0].astype(np.float64))


def test_lower_kelvin_cools_and_positive_tint_greens_the_image() -> None:
    # Saying the light was warmer (or more magenta) than the camera thought removes that
    # colour: the image's whites turn cooler (bluer) or greener.
    as_shot_kelvin, as_shot_tint = xy_to_kelvin_tint(AS_SHOT)
    white = np.ones((1, 1, 3), dtype=np.float32)
    warmer = rebalance_white(white, AS_SHOT, kelvin_tint_to_xy(3500.0, as_shot_tint))
    kelvin, _ = xy_to_kelvin_tint(_chromaticity_of_white(warmer))
    assert kelvin > 6504.0 + 500.0  # bluer than D65
    magenta = rebalance_white(white, AS_SHOT, kelvin_tint_to_xy(as_shot_kelvin, 30.0))
    _, tint = xy_to_kelvin_tint(_chromaticity_of_white(magenta))
    _, d65_tint = xy_to_kelvin_tint(D65)
    assert tint < d65_tint - 10.0  # greener than D65


def test_override_white_keeps_the_as_shot_value_of_the_other() -> None:
    kelvin, tint = xy_to_kelvin_tint(AS_SHOT)
    only_kelvin = override_white(NormaliseOverrides(wb_kelvin=3000.0), AS_SHOT)
    only_tint = override_white(NormaliseOverrides(tint=-25.0), AS_SHOT)
    both = override_white(NormaliseOverrides(wb_kelvin=3000.0, tint=-25.0), AS_SHOT)
    assert only_kelvin == pytest.approx(kelvin_tint_to_xy(3000.0, tint), abs=1e-9)
    assert only_tint == pytest.approx(kelvin_tint_to_xy(kelvin, -25.0), abs=1e-9)
    assert both == pytest.approx(kelvin_tint_to_xy(3000.0, -25.0), abs=1e-12)


def test_override_white_is_none_without_an_override() -> None:
    assert override_white(NormaliseOverrides(exposure_ev=1.0), None) is None


def test_override_white_needs_the_as_shot_white() -> None:
    with pytest.raises(WhiteBalanceOverrideError, match="as-shot"):
        override_white(NormaliseOverrides(tint=10.0), None)


def test_reddest_as_shot_white_still_works_with_a_tint_override() -> None:
    reddest = kelvin_tint_to_xy(1667.0, 0.0)
    assert override_white(NormaliseOverrides(tint=5.0), reddest) is not None
