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
