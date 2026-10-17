from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import get_args

import numpy as np
import pytest

from picturesq.colour.spaces import REC709_TO_REC2020
from picturesq.config.project import DecodeConfig
from picturesq.decode import DecodeError, decode_original
from picturesq.decode.raw import (
    DEMOSAIC_ALGORITHMS,
    HIGHLIGHT_MODES,
    camera_to_working_matrix,
    default_crop_box,
)


def test_demosaic_table_covers_every_config_value() -> None:
    literal = DecodeConfig.model_fields["demosaic"].annotation
    assert set(DEMOSAIC_ALGORITHMS) == set(get_args(literal))


def test_highlight_table_covers_every_config_value() -> None:
    literal = DecodeConfig.model_fields["highlight_mode"].annotation
    assert set(HIGHLIGHT_MODES) == set(get_args(literal))


def test_non_raw_file_raises_decode_error(tmp_path: Path) -> None:
    junk = tmp_path / "junk.dng"
    junk.write_bytes(b"not a raw file" * 100)
    with pytest.raises(DecodeError):
        decode_original(junk, DecodeConfig())


def test_missing_file_raises_decode_error(tmp_path: Path) -> None:
    with pytest.raises(DecodeError):
        decode_original(tmp_path / "missing.raf", DecodeConfig())


def test_camera_matrix_prefers_rgb_cam_and_keeps_white() -> None:
    rgb_cam = np.array([[1.7, -0.75, 0.05, 0.0], [-0.2, 1.5, -0.3, 0.0], [-0.05, -0.45, 1.5, 0.0]])
    matrix = camera_to_working_matrix(rgb_cam, np.zeros((4, 3)))
    np.testing.assert_allclose(matrix, REC709_TO_REC2020 @ rgb_cam[:, :3])
    np.testing.assert_allclose(matrix @ np.ones(3), 1.0, atol=1e-12)


def test_camera_matrix_from_cam_xyz_keeps_white() -> None:
    # A plausible XYZ -> camera matrix (Sony-like); white-balanced camera white must map to white.
    cam_xyz = np.array([[0.69, -0.21, -0.05], [-0.45, 1.22, 0.26], [-0.04, 0.15, 0.65], [0, 0, 0]])
    matrix = camera_to_working_matrix(np.zeros((3, 4)), cam_xyz)
    np.testing.assert_allclose(matrix @ np.ones(3), 1.0, atol=1e-12)


def test_camera_matrix_missing_raises() -> None:
    with pytest.raises(ValueError):
        camera_to_working_matrix(np.zeros((3, 4)), np.zeros((4, 3)))


def _sizes(**overrides: int) -> SimpleNamespace:
    """LibRaw-like sizes: a 40x60 sensor with a 2-pixel masked left border and a crop."""
    values = {
        "height": 40,
        "width": 60,
        "top_margin": 0,
        "left_margin": 2,
        "crop_top_margin": 5,
        "crop_left_margin": 6,
        "crop_height": 30,
        "crop_width": 48,
        "flip": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_default_crop_box_in_output_coordinates() -> None:
    # The crop's origin is in raw coordinates, which include the masked border.
    assert default_crop_box(_sizes(), (40, 60)) == (5, 4, 30, 48)


def test_default_crop_box_half_size() -> None:
    assert default_crop_box(_sizes(), (20, 30)) == (2, 2, 15, 24)


@pytest.mark.parametrize(
    ("values", "shape"),
    [
        ({"crop_width": 0, "crop_height": 0}, (40, 60)),  # no crop recorded
        (
            {"crop_top_margin": 0, "crop_left_margin": 2, "crop_height": 40, "crop_width": 60},
            (40, 60),
        ),
        ({"crop_height": 39}, (40, 60)),  # runs off the bottom
        ({}, (40, 50)),  # output size doesn't match the sensor
    ],
)
def test_default_crop_box_none(values: dict[str, int], shape: tuple[int, int]) -> None:
    assert default_crop_box(_sizes(**values), shape) is None


@pytest.mark.parametrize(("flip", "turns"), [(3, 2), (5, 1), (6, -1)])
def test_default_crop_box_follows_rotation(flip: int, turns: int) -> None:
    # LibRaw rotates its output (flip 3: 180°, 5: 90° counter-clockwise, 6: 90° clockwise).
    # Cropping the rotated image must give the rotated crop.
    sensor = np.arange(40 * 60).reshape(40, 60)
    top, left, height, width = default_crop_box(_sizes(), (40, 60)) or (0, 0, 0, 0)
    expected = np.rot90(sensor[top : top + height, left : left + width], turns)
    rotated = np.rot90(sensor, turns)
    box = default_crop_box(_sizes(flip=flip), rotated.shape)
    assert box is not None
    top, left, height, width = box
    np.testing.assert_array_equal(rotated[top : top + height, left : left + width], expected)
