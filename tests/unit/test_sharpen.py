import numpy as np

from picturesq.config import SharpenConfig
from picturesq.export.sharpen import sharpen


def _edge() -> np.ndarray:
    image = np.full((20, 20, 3), 0.3, dtype=np.float32)
    image[:, 10:] = 0.6
    return image


def test_sharpen_increases_edge_contrast_without_colour() -> None:
    image = _edge()
    sharpen(image, SharpenConfig(amount=1.0, radius=1.0))
    assert image[5, 9, 0] < 0.3  # dark side darker
    assert image[5, 10, 0] > 0.6  # bright side brighter
    np.testing.assert_allclose(image[..., 0], image[..., 1], atol=1e-6)
    np.testing.assert_allclose(image[..., 1], image[..., 2], atol=1e-6)


def test_flat_areas_and_zero_amount_unchanged() -> None:
    image = _edge()
    sharpen(image, SharpenConfig(amount=1.0, radius=1.0))
    np.testing.assert_allclose(image[:, :5], 0.3, atol=1e-6)
    untouched = _edge()
    sharpen(untouched, SharpenConfig(amount=0.0))
    np.testing.assert_array_equal(untouched, _edge())
