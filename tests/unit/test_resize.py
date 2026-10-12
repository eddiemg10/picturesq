"""Tests for long-edge resizing."""

import numpy as np

from picturesq.export import resize_to_long_edge


def test_none_and_small_images_are_returned_unchanged() -> None:
    image = np.zeros((20, 30, 3), dtype=np.float32)
    assert resize_to_long_edge(image, None) is image
    assert resize_to_long_edge(image, 30) is image
    assert resize_to_long_edge(image, 100) is image


def test_landscape_and_portrait_sizes() -> None:
    landscape = np.zeros((2000, 3000, 3), dtype=np.float32)
    assert resize_to_long_edge(landscape, 1000).shape == (667, 1000, 3)
    portrait = np.zeros((3000, 2000, 3), dtype=np.float32)
    assert resize_to_long_edge(portrait, 1000).shape == (1000, 667, 3)


def test_extreme_aspect_keeps_short_edge_at_least_one() -> None:
    strip = np.zeros((1, 1000, 3), dtype=np.float32)
    assert resize_to_long_edge(strip, 10).shape == (1, 10, 3)


def test_dtype_is_float32() -> None:
    image = np.zeros((40, 60, 3), dtype=np.float32)
    assert resize_to_long_edge(image, 20).dtype == np.float32


def test_constant_colour_stays_constant() -> None:
    colour = np.array([0.0123, 0.4567, 1.7], dtype=np.float32)
    image = np.broadcast_to(colour, (64, 96, 3)).copy()
    out = resize_to_long_edge(image, 24)
    assert np.allclose(out, colour, atol=1e-5)


def test_gradient_keeps_its_mean() -> None:
    ramp = np.linspace(0.0, 1.0, 120, dtype=np.float32)
    image = np.tile(ramp[None, :, None], (60, 1, 3))
    out = resize_to_long_edge(image, 30)
    assert abs(float(out.mean()) - float(image.mean())) < 0.01
