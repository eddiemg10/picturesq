import colour
import numpy as np

from picturesq.colour.oklab import oklab_to_rec2020, rec2020_to_oklab
from picturesq.colour.spaces import REC2020_TO_XYZ, apply_matrix


def _image() -> np.ndarray:
    rng = np.random.default_rng(0)
    return (rng.random((6, 5, 3)) * 3.0 - 0.2).astype(np.float32)


def test_matches_colour_science() -> None:
    image = np.abs(_image())
    expected = colour.XYZ_to_Oklab(apply_matrix(image.astype(np.float64), REC2020_TO_XYZ))
    np.testing.assert_allclose(rec2020_to_oklab(image), expected, atol=2e-5)


def test_round_trip_including_negatives_and_highlights() -> None:
    image = _image()
    np.testing.assert_allclose(oklab_to_rec2020(rec2020_to_oklab(image)), image, atol=2e-5)


def test_grey_has_no_chroma_and_white_is_one() -> None:
    grey = np.array([[[0.18] * 3, [1.0] * 3]], dtype=np.float32)
    lab = rec2020_to_oklab(grey)
    # The published matrices are rounded to 10 digits and fitted to D65 to ~1e-4.
    np.testing.assert_allclose(lab[..., 1:], 0.0, atol=2e-4)
    assert lab[0, 1, 0] == np.float32(1.0) or abs(lab[0, 1, 0] - 1.0) < 1e-4


def test_in_place() -> None:
    image = _image()
    expected = rec2020_to_oklab(image.copy())
    assert rec2020_to_oklab(image, out=image) is image
    np.testing.assert_array_equal(image, expected)


def test_rec709_round_trip_and_matches_rec2020_path() -> None:
    from picturesq.colour.oklab import oklab_to_rec709, rec709_to_oklab
    from picturesq.colour.spaces import REC709_TO_REC2020, apply_matrix

    rng = np.random.default_rng(3)
    rgb = rng.uniform(-0.1, 1.5, (500, 3)).astype(np.float32)
    lab = rec709_to_oklab(rgb)
    np.testing.assert_allclose(
        lab, rec2020_to_oklab(apply_matrix(rgb, REC709_TO_REC2020)), atol=1e-5
    )
    np.testing.assert_allclose(oklab_to_rec709(lab), rgb, atol=1e-4)


def _out_of_gamut_blues() -> np.ndarray:
    """Saturated sky and deep blues (Oklab), pushed 1.6x past what Rec.709 can show."""
    from picturesq.colour.oklab import rec709_to_oklab

    rgb = np.array(
        [[0.2, 0.45, 0.9], [0.05, 0.2, 0.85], [0.3, 0.55, 0.95], [0.02, 0.05, 0.6]],
        dtype=np.float32,
    )
    lab = rec709_to_oklab(rgb)
    lab[:, 1:] *= 1.6
    return lab


def test_gamut_fit_keeps_oklab_hue_and_lightness() -> None:
    from picturesq.colour.oklab import fit_gamut_oklab, rec709_to_oklab

    lab = _out_of_gamut_blues()
    rgb = fit_gamut_oklab(lab.copy())
    assert rgb.min() >= 0.0 and rgb.max() <= 1.0
    fitted = rec709_to_oklab(rgb)
    hue_in = np.degrees(np.arctan2(lab[:, 2], lab[:, 1]))
    hue_out = np.degrees(np.arctan2(fitted[:, 2], fitted[:, 1]))
    assert np.abs(hue_out - hue_in).max() < 0.2
    np.testing.assert_allclose(fitted[:, 0], lab[:, 0], atol=2e-3)
    # As much chroma as fits: a slightly larger value would leave the gamut.
    assert (np.hypot(fitted[:, 1], fitted[:, 2]) < np.hypot(lab[:, 1], lab[:, 2])).all()


def test_gamut_fit_beats_a_linear_pull_toward_grey_on_blues() -> None:
    """The linear-RGB pull to grey (what saturation used) bends blues; Oklab's doesn't."""
    from picturesq.colour.oklab import fit_gamut_oklab, oklab_to_rec709, rec709_to_oklab
    from picturesq.colour.spaces import REC709_TO_XYZ

    lab = _out_of_gamut_blues()
    linear = oklab_to_rec709(lab.copy())
    grey = (linear @ REC709_TO_XYZ[1].astype(np.float32))[:, None]
    scale = np.ones_like(grey)
    high, low = linear.max(1, keepdims=True), linear.min(1, keepdims=True)
    np.minimum(scale, (1 - grey) / (high - grey), out=scale, where=high > 1)
    np.minimum(scale, grey / (grey - low), out=scale, where=low < 0)
    pulled = rec709_to_oklab(grey + (linear - grey) * scale)
    fitted = rec709_to_oklab(fit_gamut_oklab(lab.copy()))
    hue = np.degrees(np.arctan2(lab[:, 2], lab[:, 1]))

    def drift(x: np.ndarray) -> float:
        return float(np.abs(np.degrees(np.arctan2(x[:, 2], x[:, 1])) - hue).max())

    assert drift(fitted) < 0.2 < drift(pulled)


def test_gamut_fit_leaves_in_gamut_pixels_alone() -> None:
    from picturesq.colour.oklab import fit_gamut_oklab, rec709_to_oklab

    rgb = np.array([[0.2, 0.4, 0.6], [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]], dtype=np.float32)
    np.testing.assert_allclose(fit_gamut_oklab(rec709_to_oklab(rgb)), rgb, atol=1e-5)


def test_gamut_fit_is_continuous_at_the_tolerance_edge() -> None:
    # A pixel just inside the tolerance is clipped; one just outside is fitted. Both must
    # land in the same place, or float rounding (memory layout, platform) flips the result.
    from picturesq.colour.oklab import GAMUT_TOLERANCE, fit_gamut_oklab, oklab_to_rec709

    colour = np.array([[0.97, -0.1, 0.02]], dtype=np.float32)

    def over(scale: float) -> float:
        lab = colour * np.array([1.0, scale, scale], dtype=np.float32)
        return float(np.abs(oklab_to_rec709(lab) - 0.5).max() - 0.5)

    low, high = 0.0, 1.0
    assert over(high) > GAMUT_TOLERANCE
    for _ in range(60):
        mid = 0.5 * (low + high)
        low, high = (mid, high) if over(mid) <= GAMUT_TOLERANCE else (low, mid)
    inside = colour * np.array([1.0, low * (1 - 1e-6), low * (1 - 1e-6)], dtype=np.float32)
    outside = colour * np.array([1.0, high * (1 + 1e-6), high * (1 + 1e-6)], dtype=np.float32)
    np.testing.assert_allclose(fit_gamut_oklab(inside), fit_gamut_oklab(outside), atol=1e-5)
