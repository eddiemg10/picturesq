"""Colour operations: vibrance, hsl and split_tone (Oklab)."""

import numpy as np
import pytest

from picturesq.colour.oklab import oklab_to_rec2020, rec2020_to_oklab
from picturesq.config.operations import (
    HUE_BANDS,
    VIBRANCE_FULL_CHROMA,
    HslOperation,
    HueBand,
    SplitToneOperation,
    ToneTint,
    VibranceOperation,
)
from picturesq.grade.operations import apply_operation, hue_band_table


def _lab_pixels(lightness: float, chroma: float, hues: np.ndarray) -> np.ndarray:
    """Linear Rec.2020 pixels with the given Oklab lightness, chroma and hues (degrees)."""
    angles = np.radians(hues)
    lab = np.stack(
        [np.full_like(angles, lightness), chroma * np.cos(angles), chroma * np.sin(angles)], -1
    ).astype(np.float32)
    return oklab_to_rec2020(lab)[None]


def _lch(image: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lab = rec2020_to_oklab(image.copy())[0]
    hue = np.degrees(np.arctan2(lab[:, 2], lab[:, 1])) % 360.0
    return lab[:, 0], np.hypot(lab[:, 1], lab[:, 2]), hue


HUES = np.arange(0.0, 360.0, 7.5)


def _every_band(band: HueBand) -> HslOperation:
    return HslOperation.model_validate({name: band for name in HUE_BANDS})


def test_vibrance_lifts_muted_colours_more() -> None:
    muted = _lab_pixels(0.6, 0.05, HUES)
    vivid = _lab_pixels(0.6, 0.2, HUES)
    for image in (muted, vivid):
        apply_operation(image, VibranceOperation(amount=0.5))
    _, muted_chroma, _ = _lch(muted)
    _, vivid_chroma, _ = _lch(vivid)
    np.testing.assert_allclose(muted_chroma, 0.05 * (1 + 0.5 * 0.8), rtol=1e-3)
    np.testing.assert_allclose(vivid_chroma, 0.2 * (1 + 0.5 * 0.2), rtol=1e-3)


def test_vibrance_keeps_saturated_colours_lightness_and_hue() -> None:
    image = _lab_pixels(0.6, VIBRANCE_FULL_CHROMA + 0.02, HUES)
    before = _lch(image)
    apply_operation(image, VibranceOperation(amount=1.0), 1.5)
    after = _lch(image)
    for b, a in zip(before, after, strict=True):
        np.testing.assert_allclose(a, b, atol=1e-3)


def test_negative_vibrance_never_inverts_colour() -> None:
    image = _lab_pixels(0.6, 0.02, HUES)
    apply_operation(image, VibranceOperation(amount=-1.0), 1.5)
    _, chroma, _ = _lch(image)
    assert (chroma < 1e-3).all()


def test_hue_band_weights_sum_to_one() -> None:
    every = HueBand(hue=1.0, chroma=1.0, lightness=1.0)
    operation = _every_band(every)
    _, changes = hue_band_table(operation)
    np.testing.assert_allclose(changes, 1.0, atol=1e-12)


def test_hue_bands_are_seamless() -> None:
    _, changes = hue_band_table(HslOperation(blue=HueBand(hue=20.0, chroma=0.5, lightness=-1.0)))
    wrapped = np.concatenate([changes, changes[:1]])
    # 0.25 degree steps; the steepest blend (40 degrees, blue to purple) moves 1/80 per degree.
    assert np.abs(np.diff(wrapped, axis=0)).max() / np.abs(changes).max(axis=0).max() < 0.02


@pytest.mark.parametrize(("name", "centre"), list(HUE_BANDS.items()))
def test_a_band_centre_gets_its_whole_change(name: str, centre: float) -> None:
    image = _lab_pixels(0.6, 0.1, np.array([centre]))
    apply_operation(image, HslOperation.model_validate({name: {"hue": 10.0, "chroma": -0.5}}))
    lightness, chroma, hue = _lch(image)
    assert lightness[0] == pytest.approx(0.6, abs=1e-4)
    assert chroma[0] == pytest.approx(0.05, abs=1e-4)
    assert hue[0] == pytest.approx((centre + 10.0) % 360.0, abs=0.05)


def test_hsl_leaves_other_bands_alone() -> None:
    image = _lab_pixels(0.6, 0.1, np.array([HUE_BANDS["green"]]))
    before = image.copy()
    apply_operation(image, HslOperation(blue=HueBand(hue=10.0, chroma=-0.5, lightness=-1.0)))
    np.testing.assert_allclose(image, before, atol=1e-5)


def test_hsl_leaves_greys_alone() -> None:
    grey = np.full((1, 4, 3), 0.18, dtype=np.float32)
    before = grey.copy()
    everything = HueBand(hue=30.0, chroma=1.0, lightness=1.0)
    apply_operation(grey, _every_band(everything))
    np.testing.assert_allclose(grey, before, atol=1e-5)


def test_hsl_lightness_darkens_a_blue_sky_in_stops() -> None:
    sky = _lab_pixels(0.7, 0.1, np.array([HUE_BANDS["blue"]]))
    before = sky.copy()
    apply_operation(sky, HslOperation(blue=HueBand(lightness=-0.5)))
    np.testing.assert_allclose(sky, before * 2.0**-0.5, rtol=1e-4)


def test_split_tone_keeps_black_and_lightness() -> None:
    image = np.array([[[0.0, 0.0, 0.0], [0.05, 0.05, 0.05], [0.8, 0.8, 0.8]]], dtype=np.float32)
    lightness_before, _, _ = _lch(image)
    operation = SplitToneOperation(
        shadows=ToneTint(hue=220.0, amount=0.5), highlights=ToneTint(hue=60.0, amount=0.5)
    )
    apply_operation(image, operation)
    lightness, chroma, hue = _lch(image)
    np.testing.assert_array_equal(image[0, 0], 0.0)
    np.testing.assert_allclose(lightness, lightness_before, atol=1e-4)
    assert hue[1] == pytest.approx(220.0, abs=2.0)  # dark grey: mostly the shadow hue
    assert hue[2] == pytest.approx(60.0, abs=2.0)  # bright grey: mostly the highlight hue
    assert chroma[1] > 0.01 and chroma[2] > 0.01


def test_split_tone_amount_one_adds_its_chroma_at_mid_grey() -> None:
    grey = np.full((1, 1, 3), 0.18, dtype=np.float32)
    tint = ToneTint(hue=200.0, amount=1.0)
    apply_operation(grey, SplitToneOperation(shadows=tint, highlights=tint))
    _, chroma, _ = _lch(grey)
    assert chroma[0] == pytest.approx(0.1, rel=1e-3)


def test_split_tone_balance_moves_the_crossover() -> None:
    grey = np.full((1, 1, 3), 0.18, dtype=np.float32)
    results = []
    for balance in (-1.0, 0.0, 1.0):
        image = grey.copy()
        operation = SplitToneOperation(shadows=ToneTint(hue=220.0, amount=1.0), balance=balance)
        apply_operation(image, operation)
        results.append(_lch(image)[1][0])
    low, middle, high = results
    assert low < middle < high
    assert middle == pytest.approx(0.05, rel=3e-3)  # half shadows, half highlights at mid grey
