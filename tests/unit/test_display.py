import numpy as np

from picturesq.colour.display import display_transform


def _image() -> np.ndarray:
    rng = np.random.default_rng(0)
    return (rng.random((8, 6, 3), dtype=np.float32) * 2.0 - 0.2).astype(np.float32)


def test_dtype_and_shape() -> None:
    result = display_transform(_image())
    assert result.dtype == np.float32
    assert result.shape == (8, 6, 3)


def test_white_stays_white() -> None:
    white = np.ones((2, 2, 3), dtype=np.float32)
    np.testing.assert_allclose(display_transform(white), 1.0, atol=1e-5)


def test_neutral_greys_stay_neutral() -> None:
    levels = np.linspace(0.0, 1.0, 11, dtype=np.float32)
    grey = np.repeat(levels[:, None, None], 3, axis=2)
    result = display_transform(grey)
    np.testing.assert_allclose(result[..., 0], result[..., 1], atol=1e-5)
    np.testing.assert_allclose(result[..., 1], result[..., 2], atol=1e-5)
    np.testing.assert_allclose(result[..., 0], grey[..., 0], atol=1e-5)


def test_output_in_unit_range() -> None:
    result = display_transform(_image())
    assert result.min() >= 0.0
    assert result.max() <= 1.0


def test_out_parameter() -> None:
    image = _image()
    expected = display_transform(image.copy())
    out = np.empty_like(image)
    result = display_transform(image, out=out)
    assert result is out
    np.testing.assert_array_equal(out, expected)
    in_place = display_transform(image, out=image)
    assert in_place is image
    np.testing.assert_array_equal(image, expected)
