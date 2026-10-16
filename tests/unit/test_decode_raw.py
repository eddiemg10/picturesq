from __future__ import annotations

from pathlib import Path
from typing import get_args

import numpy as np
import pytest

from picturesq.colour.spaces import REC709_TO_REC2020
from picturesq.config.project import DecodeConfig
from picturesq.decode import DecodeError, decode_original
from picturesq.decode.raw import DEMOSAIC_ALGORITHMS, HIGHLIGHT_MODES, camera_to_working_matrix


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
