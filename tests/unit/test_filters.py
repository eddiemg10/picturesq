import numpy as np
import pytest

from picturesq.colour.filters import box_blur, gaussian_blur, gaussian_blur_plane, upsample_rows


def test_box_blur_mean_and_edges() -> None:
    row = np.array([[0.0, 0.0, 3.0, 0.0, 0.0]], dtype=np.float32)
    np.testing.assert_allclose(box_blur(row, 1, axis=1), [[0.0, 1.0, 1.0, 1.0, 0.0]], atol=1e-6)
    flat = np.full((4, 7), 2.5, dtype=np.float32)
    np.testing.assert_allclose(box_blur(flat, 3, axis=0), 2.5, atol=1e-6)


@pytest.mark.parametrize(
    "blur", [lambda p: gaussian_blur(p, 2.0), lambda p: gaussian_blur_plane(p, 1.0)]
)
def test_blurs_preserve_mean_and_flat_fields(blur) -> None:
    rng = np.random.default_rng(0)
    noise = rng.random((40, 50)).astype(np.float32)
    blurred = blur(noise)
    assert blurred.shape == noise.shape
    assert abs(blurred.mean() - noise.mean()) < 0.01
    assert blurred.std() < noise.std() / 2
    flat = np.full((20, 30), 0.7, dtype=np.float32)
    np.testing.assert_allclose(blur(flat), 0.7, atol=1e-5)


def test_gaussian_blur_plane_matches_variance() -> None:
    impulse = np.zeros((41, 41), dtype=np.float32)
    impulse[20, 20] = 1.0
    blurred = gaussian_blur_plane(impulse, 2.0)
    xs = np.arange(41) - 20
    variance = (blurred.sum(axis=0) * xs**2).sum()
    assert variance == pytest.approx(4.0, rel=0.02)


def test_upsample_rows_matches_whole_image_and_constant() -> None:
    rng = np.random.default_rng(1)
    small = rng.random((5, 7, 2)).astype(np.float32)
    whole = upsample_rows(small, 23, 31, 0, 23)
    assert whole.shape == (23, 31, 2)
    np.testing.assert_allclose(upsample_rows(small, 23, 31, 9, 15), whole[9:15], atol=1e-6)
    assert whole.min() >= small.min() - 1e-6
    assert whole.max() <= small.max() + 1e-6
    constant = np.full((3, 3, 1), 0.4, dtype=np.float32)
    np.testing.assert_allclose(upsample_rows(constant, 10, 10, 0, 10), 0.4, atol=1e-6)
