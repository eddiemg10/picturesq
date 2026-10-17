"""The DNG-specification camera matrix (ADR-0012), on synthetic cameras."""

from pathlib import Path

import numpy as np
import pytest

from picturesq.colour.spaces import REC2020_TO_XYZ, XYZ_TO_REC2020
from picturesq.colour.temperature import bradford_matrix, xy_to_cct, xy_to_xyz
from picturesq.decode.dng_colour import (
    D50,
    D65,
    DngColour,
    _weight_for,
    dng_camera_to_working,
    read_dng_colour,
)

# A plausible camera: XYZ -> camera RGB (rows roughly R, G, B sensitivities).
CAMERA = np.array([[1.10, -0.20, -0.10], [-0.45, 1.35, 0.10], [-0.05, 0.15, 0.55]])
TUNGSTEN_CAMERA = CAMERA @ np.diag([1.08, 1.0, 0.85])  # a differently fitted second matrix


def _neutral(xyz_to_camera: np.ndarray, xy: tuple[float, float]) -> np.ndarray:
    return xyz_to_camera @ xy_to_xyz(xy)


def test_white_balanced_white_maps_to_white() -> None:
    dng = DngColour((CAMERA,), (6500.0,), as_shot_neutral=_neutral(CAMERA, (0.40, 0.39)))
    matrix, _ = dng_camera_to_working(dng)
    assert np.allclose(matrix @ np.ones(3), 1.0, atol=1e-12)


def test_single_matrix_is_colorimetric_for_a_d65_scene() -> None:
    # A colour seen by the camera under a D65 white comes out as its own Rec.2020 value.
    neutral = _neutral(CAMERA, D65)
    matrix, white = dng_camera_to_working(DngColour((CAMERA,), (6500.0,), as_shot_neutral=neutral))
    rec2020 = np.array([0.1, 0.25, 0.6])
    camera_rgb = CAMERA @ (REC2020_TO_XYZ @ rec2020)
    white_balanced = camera_rgb / neutral
    out = matrix @ white_balanced
    scale = 1.0 / (XYZ_TO_REC2020 @ xy_to_xyz(D65)).mean()  # (1,1,1) normalisation
    assert np.allclose(out, rec2020 * scale, atol=1e-9)
    assert white.kelvin == pytest.approx(6504, abs=2)


def test_identical_matrices_ignore_the_weight() -> None:
    neutral = _neutral(CAMERA, (0.42, 0.40))
    one, _ = dng_camera_to_working(DngColour((CAMERA,), (2850.0,), as_shot_neutral=neutral))
    two, _ = dng_camera_to_working(
        DngColour((CAMERA, CAMERA), (2850.0, 6500.0), as_shot_neutral=neutral)
    )
    assert np.allclose(one, two, atol=1e-12)


@pytest.mark.parametrize("xy", [(0.3127, 0.3290), (0.38, 0.38), (0.44, 0.40)])
def test_weight_is_consistent_with_the_white_it_implies(xy: tuple[float, float]) -> None:
    # Fixed point of the DNG procedure: the weight gives a white whose temperature gives it back.
    neutral = _neutral(0.5 * (CAMERA + TUNGSTEN_CAMERA), xy)
    dng = DngColour((TUNGSTEN_CAMERA, CAMERA), (2850.0, 6500.0), as_shot_neutral=neutral)
    _, white = dng_camera_to_working(dng)
    assert white.weight == pytest.approx(_weight_for(white.kelvin, (2850.0, 6500.0)), abs=1e-6)
    assert white.kelvin == pytest.approx(xy_to_cct(white.xy))


def test_warmer_white_uses_more_of_the_tungsten_matrix() -> None:
    def weight(xy: tuple[float, float]) -> float:
        dng = DngColour(
            (TUNGSTEN_CAMERA, CAMERA), (2850.0, 6500.0), as_shot_neutral=_neutral(CAMERA, xy)
        )
        return dng_camera_to_working(dng)[1].weight

    assert weight((0.3127, 0.3290)) < weight((0.38, 0.38)) < weight((0.44, 0.40))


def test_forward_matrix_path_agrees_with_colour_matrix_path() -> None:
    # A forward matrix consistent with the colour matrix (as profile makers derive it).
    neutral = _neutral(CAMERA, D65)
    forward = bradford_matrix(D65, D50) @ np.linalg.inv(CAMERA) @ np.diag(neutral)
    without, _ = dng_camera_to_working(DngColour((CAMERA,), (6500.0,), as_shot_neutral=neutral))
    with_fm, _ = dng_camera_to_working(
        DngColour((CAMERA,), (6500.0,), forward_matrices=(forward,), as_shot_neutral=neutral)
    )
    assert np.allclose(without, with_fm, atol=1e-9)


def test_as_shot_white_xy_is_used_without_a_neutral() -> None:
    xy = (0.40, 0.39)
    by_xy, _ = dng_camera_to_working(DngColour((CAMERA,), (6500.0,), as_shot_white_xy=xy))
    by_neutral, _ = dng_camera_to_working(
        DngColour((CAMERA,), (6500.0,), as_shot_neutral=_neutral(CAMERA, xy))
    )
    assert np.allclose(by_xy, by_neutral, atol=1e-9)


def test_non_tiff_file_has_no_dng_colour(tmp_path: Path) -> None:
    path = tmp_path / "photo.raf"
    path.write_bytes(b"FUJIFILMCCD-RAW not a tiff")
    assert read_dng_colour(path) is None
