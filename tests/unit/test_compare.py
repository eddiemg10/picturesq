import numpy as np
import pytest
from PIL import Image

from picturesq.colour.oklab import oklab_to_rec709, rec709_to_oklab
from picturesq.colour.transfer import srgb_decode, srgb_encode
from picturesq.preview.compare import (
    MIN_CONTENT_CORRELATION,
    PhotoComparison,
    align,
    aligned_chroma_by_band,
    chroma_by_band,
    compare_photo,
    content_correlation,
    gate,
    pooled_difference,
)


def _gradient(width: int = 120, height: int = 80) -> np.ndarray:
    x = np.linspace(20, 230, width, dtype=np.float32)
    y = np.linspace(0.6, 1.0, height, dtype=np.float32)[:, None]
    rgb = np.stack([x * y, x * y * 0.8, x * y * 0.5], axis=-1)
    return rgb.astype(np.uint8)


def test_identical_images_compare_equal() -> None:
    image = _gradient()
    result = compare_photo("a", image, image)
    assert result.ev_difference == pytest.approx(0.0)
    assert result.same_frame
    ratios = [r for r in result.chroma_ratio if not np.isnan(r)]
    np.testing.assert_allclose(ratios, 1.0)


def test_brighter_image_has_positive_ev() -> None:
    image = _gradient()
    brighter = np.clip(image.astype(np.int32) + 40, 0, 255).astype(np.uint8)
    assert compare_photo("a", brighter, image).ev_difference > 0.2


def test_different_frame_detected_and_left_out() -> None:
    image = _gradient()
    other = image[:, ::-1].copy()
    assert content_correlation(image, other) < MIN_CONTENT_CORRELATION
    good = compare_photo("good", image, image)
    bad = compare_photo("bad", np.clip(image.astype(np.int32) * 3, 0, 255).astype(np.uint8), other)
    assert gate([good, bad]).passed


def test_grey_has_no_chroma() -> None:
    grey = np.full((40, 40, 3), 128, dtype=np.uint8)
    chroma = chroma_by_band(grey)
    assert np.nanmax(chroma) < 1e-3


def _photo(ev: float, clipped: float = 0.0, chroma: float = 0.1) -> PhotoComparison:
    return PhotoComparison("p", ev, clipped, 0.0, (chroma,) * 6, (0.1,) * 6, 1.0)


def test_gate_thresholds() -> None:
    assert gate([_photo(0.3), _photo(-0.4)]).passed
    assert not gate([_photo(0.8), _photo(-0.9)]).brightness_ok
    assert not gate([_photo(0.0, chroma=0.15)]).colour_ok
    assert not gate([_photo(0.0, clipped=0.02)]).highlights_ok


def _banded(ours: tuple[float, ...], camera: tuple[float, ...]) -> PhotoComparison:
    return PhotoComparison("p", 0.0, 0.0, 0.0, ours, camera, 1.0)


def test_near_white_passes_on_a_small_absolute_difference() -> None:
    # Near-white: 0.0167 against 0.0067 is 2.5x but only 0.01 apart, below a visible tint.
    result = gate([_banded((0.1,) * 5 + (0.0167,), (0.1,) * 5 + (0.0067,))])
    assert result.band_chroma_ratio[-1] == pytest.approx(2.5, rel=0.01)
    assert result.band_chroma_difference[-1] == pytest.approx(0.01)
    assert result.colour_ok
    assert result.band_on_tolerance == (False,) * 5 + (True,)


def test_large_difference_out_of_range_fails() -> None:
    result = gate([_banded((0.1,) * 5 + (0.06,), (0.1,) * 5 + (0.03,))])
    assert result.band_chroma_difference[-1] == pytest.approx(0.03)
    assert not result.colour_ok
    assert not any(result.band_on_tolerance)


def test_ratio_in_range_passes_whatever_the_difference() -> None:
    # 1.2x of a strongly coloured band: 0.04 apart, but the ratio is within range.
    result = gate([_banded((0.24,) * 6, (0.2,) * 6)])
    assert result.band_chroma_difference[0] == pytest.approx(0.04)
    assert result.colour_ok
    assert not any(result.band_on_tolerance)


def test_pooled_difference_leaves_out_missing_bands() -> None:
    nan = float("nan")
    ours = [(0.02, nan), (0.04, 0.1)]
    camera = [(0.01, 0.2), (0.01, nan)]
    difference = pooled_difference(ours, camera)
    assert difference[0] == pytest.approx(0.02)
    assert np.isnan(difference[1])


def _scene(width: int = 400, height: int = 300) -> np.ndarray:
    """Coloured blobs on a gradient: content that phase correlation can lock onto."""
    rng = np.random.default_rng(3)
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    rgb = np.stack([x / width, y / height, 0.5 + 0.0 * x], axis=-1) * 120.0 + 40.0
    for _ in range(25):
        cy, cx, r = rng.random(3) * [height, width, 30.0] + [0, 0, 8.0]
        inside = (y - cy) ** 2 + (x - cx) ** 2 < r**2
        rgb[inside] = rng.random(3) * 120.0 + 70.0  # moderate chroma: stays in gamut darker
    return rgb.astype(np.uint8)


def test_align_recovers_crop_zoom_and_offset() -> None:
    # The camera JPEG shows a 3:2-ish window of our 4:3 frame: 95 % of the width, a few
    # pixels off centre, and smaller.
    ours = _scene(400, 300)
    window = ours[44:261, 13:393]
    camera = np.asarray(Image.fromarray(window).resize((297, 170), Image.Resampling.BOX))
    a, b = align(ours, camera)
    assert a.shape == b.shape
    assert a.shape[0] > 160 and a.shape[1] > 285  # little of the frame is lost
    assert content_correlation(a, b) > 0.98


def test_aligned_colour_is_blind_to_a_brightness_difference() -> None:
    # Ours has the camera's colours (same Oklab a, b at every pixel) but is darker. Banding
    # each image by its own lightness puts different pixels in each band and reports a
    # colour difference; banding both by the camera's lightness does not (#58).
    camera = _scene()
    lab = rec709_to_oklab(srgb_decode(camera.astype(np.float32) / 255.0).reshape(-1, 3))
    lab[:, 0] *= 0.8
    rgb = srgb_encode(np.clip(oklab_to_rec709(lab), 0.0, 1.0)).reshape(camera.shape)
    darker = np.round(rgb * 255.0).astype(np.uint8)

    ours_chroma, camera_chroma = aligned_chroma_by_band(*align(darker, camera))
    both = ~(np.isnan(ours_chroma) | np.isnan(camera_chroma))
    np.testing.assert_allclose(ours_chroma[both], camera_chroma[both], rtol=0.05)
    own, camera_own = chroma_by_band(darker), chroma_by_band(camera)
    ratios = own / camera_own
    assert np.nanmax(np.abs(np.log(ratios))) > np.log(1.25)  # the old measure fails the gate
