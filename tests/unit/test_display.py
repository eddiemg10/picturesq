import numpy as np

from picturesq.colour.display import display_transform
from picturesq.config import DisplayTransformConfig


def _image() -> np.ndarray:
    rng = np.random.default_rng(0)
    return (rng.random((8, 6, 3), dtype=np.float32) * 2.0 - 0.2).astype(np.float32)


def test_dtype_and_shape() -> None:
    result = display_transform(_image())
    assert result.dtype == np.float32
    assert result.shape == (8, 6, 3)


def test_neutral_greys_stay_neutral() -> None:
    levels = np.linspace(0.0, 4.0, 11, dtype=np.float32)
    grey = np.repeat(levels[:, None, None], 3, axis=2)
    result = display_transform(grey)
    np.testing.assert_allclose(result[..., 0], result[..., 1], atol=1e-5)
    np.testing.assert_allclose(result[..., 1], result[..., 2], atol=1e-5)


def test_output_in_unit_range() -> None:
    result = display_transform(_image() * np.float32(100.0))
    assert result.min() >= 0.0
    assert result.max() <= 1.0


def test_config_is_used() -> None:
    grey = np.full((1, 1, 3), 2.0, dtype=np.float32)
    default = display_transform(grey.copy())
    darker = display_transform(grey.copy(), DisplayTransformConfig(max_ev=11.0))
    assert darker[0, 0, 0] < default[0, 0, 0]


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
