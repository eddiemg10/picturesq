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


def _glints_on_water() -> np.ndarray:
    """Dark water (0.4) with a grid of tiny glints 100x brighter, as after normalise + grade."""
    image = np.full((240, 360, 3), 0.4, dtype=np.float32)
    image[3::9, 5::11] = 40.0
    image[4::9, 5::11] = 40.0
    return image


def test_glints_do_not_ring_below_the_darkest_source_pixel() -> None:
    # Plain Lanczos takes pixels next to such glints far below 0 (black speckle, #55).
    out = resize_to_long_edge(_glints_on_water(), 96)
    assert out.min() >= 0.4 - 1e-4


def test_output_stays_within_the_local_source_range() -> None:
    rng = np.random.default_rng(0)
    image = rng.uniform(0.0, 1.0, (200, 300, 3)).astype(np.float32)
    image[rng.uniform(size=(200, 300)) < 0.01] = 50.0
    out = resize_to_long_edge(image, 75)
    assert out.min() >= 0.0
    assert out.max() <= 50.0 + 1e-3


def test_ordinary_edges_keep_lanczos_sharpness() -> None:
    # A modest step: the clamp must not soften it to a box filter's ramp.
    from PIL import Image

    image = np.zeros((60, 600, 3), dtype=np.float32)
    image[:, 300:] = 1.0
    image[:, 150:300] = 0.5
    out = resize_to_long_edge(image, 200)
    plane = Image.fromarray(np.ascontiguousarray(image[..., 0]))
    lanczos = np.asarray(plane.resize((200, 20), Image.Resampling.LANCZOS))
    inside = (lanczos >= 0.0) & (lanczos <= 1.0)
    assert np.allclose(out[..., 0][inside], lanczos[inside], atol=0.02)


def test_planes_copied_in_row_bands_match_whole_plane_copies() -> None:
    """Pillow gets each channel a band of rows at a time; its plane must be the same."""
    from PIL import Image

    from picturesq import parallel
    from picturesq.export.resize import _pillow_plane

    rng = np.random.default_rng(3)
    image = (rng.random((97, 143, 3), dtype=np.float32) * 5.0).astype(np.float32)
    with parallel.using(parallel.Parallelism(threads=1, block_pixels=500)):  # 28 bands
        for channel in range(3):
            whole = Image.fromarray(np.ascontiguousarray(image[..., channel]))
            banded = _pillow_plane(image, channel)
            np.testing.assert_array_equal(np.asarray(banded), np.asarray(whole))
