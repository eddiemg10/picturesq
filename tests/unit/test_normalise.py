import numpy as np
import pytest

from picturesq.colour.oklab import rec2020_to_oklab
from picturesq.colour.spaces import REC2020_TO_XYZ
from picturesq.config import ChromaNoiseReductionConfig, ExposureConfig, ProjectConfig
from picturesq.normalise import chroma_noise_reduction, exposure_ev, median_ev, normalise
from picturesq.photo import PhotoContext


def _grey(value: float, shape: tuple[int, int] = (40, 60)) -> np.ndarray:
    return np.full((*shape, 3), value, dtype=np.float32)


def test_median_ev_of_grey() -> None:
    assert median_ev(_grey(0.18)) == pytest.approx(0.0, abs=1e-5)
    assert median_ev(_grey(0.045)) == pytest.approx(-2.0, abs=1e-5)


def test_exposure_is_offset_without_correction() -> None:
    config = ExposureConfig(offset_ev=2.0)
    assert exposure_ev(_grey(0.01), config) == 2.0
    assert exposure_ev(_grey(1.0), config) == 2.0


def test_partial_correction_and_clamp() -> None:
    config = ExposureConfig(offset_ev=0.0, correction=0.5, target_ev=0.0, max_correction_ev=2.0)
    assert exposure_ev(_grey(0.045), config) == pytest.approx(1.0, abs=1e-5)  # half of +2
    far = ExposureConfig(offset_ev=0.0, correction=1.0, target_ev=0.0, max_correction_ev=2.0)
    assert exposure_ev(_grey(0.18 / 64), far) == pytest.approx(2.0)  # +6 clamped to +2


def test_normalise_applies_gain_in_place() -> None:
    image = _grey(0.1)
    result = normalise(image, ProjectConfig())
    assert result is image
    np.testing.assert_allclose(image, 0.1 * 2.0**2.0, rtol=1e-5)


def test_normalise_disabled_is_identity() -> None:
    config = ProjectConfig.model_validate({"normalise": {"enabled": False}})
    image = _grey(0.1)
    np.testing.assert_array_equal(normalise(image, config), np.float32(0.1))


def _noisy(level: float) -> np.ndarray:
    rng = np.random.default_rng(0)
    image = np.full((120, 160, 3), level, dtype=np.float32)
    image *= 1.0 + 0.3 * rng.standard_normal((120, 160, 3)).astype(np.float32)
    return np.maximum(image, 1e-4)


def _chroma_noise(image: np.ndarray) -> float:
    return float(rec2020_to_oklab(image)[..., 1:].std())


def test_chroma_nr_removes_colour_noise_in_shadows_only() -> None:
    config = ChromaNoiseReductionConfig()
    dark, bright = _noisy(0.005), _noisy(1.0)
    dark_before, bright_before = _chroma_noise(dark), _chroma_noise(bright)
    luminance_before = dark @ REC2020_TO_XYZ[1].astype(np.float32)
    chroma_noise_reduction(dark, config)
    chroma_noise_reduction(bright, config)
    assert _chroma_noise(dark) < dark_before / 3
    assert _chroma_noise(bright) == pytest.approx(bright_before, rel=1e-3)
    np.testing.assert_allclose(
        dark @ REC2020_TO_XYZ[1].astype(np.float32), luminance_before, rtol=1e-4, atol=1e-7
    )


def test_chroma_nr_off_and_grey() -> None:
    image = _noisy(0.01)
    before = image.copy()
    chroma_noise_reduction(image, ChromaNoiseReductionConfig(amount=0.0))
    np.testing.assert_array_equal(image, before)
    grey = _grey(0.01)
    chroma_noise_reduction(grey, ChromaNoiseReductionConfig())
    np.testing.assert_allclose(grey, 0.01, rtol=1e-4)


def test_chroma_nr_config_rejects_inverted_fade() -> None:
    with pytest.raises(ValueError):
        ChromaNoiseReductionConfig(full_lightness=0.6, fade_lightness=0.5)


def test_exposure_override_replaces_the_computed_exposure() -> None:
    config = ProjectConfig.model_validate(
        {"photos": {"A.DNG": {"normalise": {"exposure_ev": 1.0}}}}
    )
    image = _grey(0.1)
    normalise(image, config, PhotoContext(name="a.dng"))
    np.testing.assert_allclose(image, 0.1 * 2.0, rtol=1e-5)
    other = _grey(0.1)
    normalise(other, config, PhotoContext(name="B.DNG"))  # no override: offset_ev 2.0
    np.testing.assert_allclose(other, 0.1 * 4.0, rtol=1e-5)
