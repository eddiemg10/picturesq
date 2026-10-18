"""Per-photo white balance overrides on a real CC0 sample (half-size decodes)."""

from pathlib import Path

import numpy as np
import pytest

from picturesq.config import ProjectConfig
from picturesq.decode import decode_original
from picturesq.pipeline.export import photo_context, render_scene

pytestmark = pytest.mark.integration

NAME = "pentax-k5iis.dng"  # a tungsten-lit interior, as-shot about 3300 K


def _render(path: Path, overrides: dict[str, object]) -> np.ndarray:
    config = ProjectConfig.model_validate({"photos": {NAME: {"normalise": overrides}}})
    image = decode_original(path, config.decode, half_size=True)
    return render_scene(image, config, photo_context(path, config))


def _blue_over_red(image: np.ndarray) -> float:
    means = image.reshape(-1, 3).mean(axis=0)
    return float(means[2] / means[0])


def test_white_balance_override_on_a_sample(samples_dir: Path) -> None:
    path = samples_dir / NAME
    if not path.is_file():
        pytest.skip(f"{NAME} not found in {samples_dir}")
    plain = _render(path, {})
    info = photo_context(path, ProjectConfig.model_validate({"photos": {NAME: {}}})).info
    assert info is None  # not read without a white balance override
    as_shot = photo_context(
        path, ProjectConfig.model_validate({"photos": {NAME: {"normalise": {"tint": 0.0}}}})
    ).info
    assert as_shot is not None and as_shot.as_shot_kelvin is not None
    same = _render(path, {"wb_kelvin": as_shot.as_shot_kelvin, "tint": as_shot.as_shot_tint})
    np.testing.assert_allclose(same, plain, atol=1e-4)
    # Saying the light was daylight, not tungsten, leaves the interior warm (less blue).
    daylight = _render(path, {"wb_kelvin": 5500.0})
    assert _blue_over_red(daylight) < 0.8 * _blue_over_red(plain)
