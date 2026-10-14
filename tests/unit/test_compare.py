import numpy as np
import pytest

from picturesq.preview.compare import (
    MIN_CONTENT_CORRELATION,
    PhotoComparison,
    chroma_by_band,
    compare_photo,
    content_correlation,
    gate,
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
