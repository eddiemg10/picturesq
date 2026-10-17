"""The camera → working-space matrix a DNG specifies, computed the way the DNG specification says.

A DNG usually carries two **colour matrices** (XYZ → camera RGB), each measured under one
**calibration illuminant**: typically tungsten (Standard light A, ~2850 K) and daylight
(D65). A renderer must *blend* them according to the photo's own white: a sunset or a
tungsten-lit room needs more of the tungsten matrix than a midday sky does. LibRaw only ever
uses the second matrix (#54), so we compute the matrix ourselves (DNG specification 1.6,
chapter 6, "Mapping Camera Color Space to CIE XYZ Space"):

1. The weight between the matrices is linear in inverse colour temperature (mired), from
   the as-shot white's correlated colour temperature, which itself depends on the blended
   matrix. We solve that circular dependency by bisection on the weight: with very
   different matrices (the DJI Pocket 4's) the plain fixed-point iteration oscillates.
2. With ``ForwardMatrix`` tags, white-balanced camera RGB → XYZ (D50) is the forward matrix;
   without them, it is the inverse of the blended colour matrix, adapted from the scene
   white to D50.
3. We then adapt D50 → D65 (Bradford) and convert XYZ → linear Rec.2020, and scale the
   whole matrix so white-balanced white maps to (1, 1, 1), as LibRaw's matrix does.

``CameraCalibration`` and ``AnalogBalance`` are honoured when present. Proprietary RAWs (no
DNG tags) keep LibRaw's matrix.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import tifffile
from numpy.typing import NDArray

from picturesq.colour.spaces import XYZ_TO_REC2020, Matrix
from picturesq.colour.temperature import bradford_matrix, xy_to_cct, xy_to_xyz, xyz_to_xy

D50: Final = (0.3457, 0.3585)
"""The DNG profile connection space white (ICC D50)."""
D65: Final = (0.3127, 0.3290)

# EXIF LightSource codes → temperature in kelvin, as the Adobe DNG SDK assigns them.
ILLUMINANT_KELVIN: Final[dict[int, float]] = {
    1: 5500.0,  # daylight
    2: 4150.0,  # fluorescent
    3: 2850.0,  # tungsten
    4: 5500.0,  # flash
    9: 5500.0,  # fine weather
    10: 6500.0,  # cloudy
    11: 7500.0,  # shade
    12: 6430.0,  # daylight fluorescent
    13: 5000.0,  # day white fluorescent
    14: 4150.0,  # cool white fluorescent
    15: 3450.0,  # white fluorescent
    16: 2940.0,  # warm white fluorescent
    17: 2850.0,  # standard light A
    18: 5500.0,  # standard light B
    19: 6500.0,  # standard light C
    20: 5500.0,  # D55
    21: 6500.0,  # D65
    22: 7500.0,  # D75
    23: 5000.0,  # D50
    24: 3200.0,  # ISO studio tungsten
}

_TAGS: Final = {
    "colour_matrix_1": 50721,
    "colour_matrix_2": 50722,
    "camera_calibration_1": 50723,
    "camera_calibration_2": 50724,
    "analogue_balance": 50727,
    "as_shot_neutral": 50728,
    "as_shot_white_xy": 50729,
    "illuminant_1": 50778,
    "illuminant_2": 50779,
    "forward_matrix_1": 50964,
    "forward_matrix_2": 50965,
}
_BISECTION_STEPS: Final = 50


@dataclass(frozen=True)
class DngColour:
    """The colour tags of one DNG (index 0: calibration illuminant 1, index 1: illuminant 2)."""

    colour_matrices: tuple[Matrix, ...]
    """XYZ → camera RGB, one per calibration illuminant (1 or 2)."""
    illuminant_kelvin: tuple[float | None, ...]
    """Temperature of each calibration illuminant; None if unknown."""
    forward_matrices: tuple[Matrix, ...] = ()
    """White-balanced camera RGB → XYZ (D50), one per illuminant, or none."""
    camera_calibrations: tuple[Matrix, ...] = ()
    analogue_balance: NDArray[np.float64] | None = None
    as_shot_neutral: NDArray[np.float64] | None = None
    """Camera RGB of the scene white (the white balance the camera recorded)."""
    as_shot_white_xy: tuple[float, float] | None = None


def _rationals(value: object, count: int) -> NDArray[np.float64] | None:
    """Tag value → ``count`` floats. tifffile gives (num, den) pairs flattened, or floats."""
    if not isinstance(value, tuple | list):
        return None
    numbers = np.asarray(value, dtype=np.float64)
    if len(numbers) == 2 * count:
        denominators = numbers[1::2]
        if np.any(denominators == 0):
            return None
        return numbers[0::2] / denominators
    if len(numbers) == count:
        return numbers
    return None


def read_dng_colour(path: Path) -> DngColour | None:
    """Read the colour tags of a DNG; None for non-DNG files or DNGs without a colour matrix."""
    try:
        with tifffile.TiffFile(path) as tiff:
            tags = tiff.pages.first.tags
            values = {
                name: (tags.get(code).value if tags.get(code) is not None else None)  # type: ignore[union-attr]
                for name, code in _TAGS.items()
            }
    except (tifffile.TiffFileError, ValueError, IndexError):
        return None

    def matrices(*names: str) -> tuple[Matrix, ...]:
        found = [_rationals(values[name], 9) for name in names]
        return tuple(m.reshape(3, 3) for m in found if m is not None)

    colour_matrices = matrices("colour_matrix_1", "colour_matrix_2")
    if not colour_matrices:
        return None
    kelvin = tuple(
        ILLUMINANT_KELVIN.get(int(v)) if isinstance(v, int) else None
        for v in (values["illuminant_1"], values["illuminant_2"])
    )[: len(colour_matrices)]
    forward = matrices("forward_matrix_1", "forward_matrix_2")
    calibration = matrices("camera_calibration_1", "camera_calibration_2")
    white_xy = _rationals(values["as_shot_white_xy"], 2)
    return DngColour(
        colour_matrices=colour_matrices,
        illuminant_kelvin=kelvin,
        forward_matrices=forward if len(forward) == len(colour_matrices) else (),
        camera_calibrations=calibration if len(calibration) == len(colour_matrices) else (),
        analogue_balance=_rationals(values["analogue_balance"], 3),
        as_shot_neutral=_rationals(values["as_shot_neutral"], 3),
        as_shot_white_xy=None if white_xy is None else (float(white_xy[0]), float(white_xy[1])),
    )


def _blend(matrices: tuple[Matrix, ...], weight: float) -> Matrix:
    """``weight`` of the first matrix and ``1 - weight`` of the second (or the only one)."""
    if len(matrices) == 1:
        return matrices[0]
    return weight * matrices[0] + (1.0 - weight) * matrices[1]


def _weight_for(kelvin: float, illuminants: tuple[float, float]) -> float:
    """Weight of illuminant 1, linear in inverse temperature and clamped to [0, 1]."""
    t1, t2 = illuminants
    return float(np.clip((1.0 / kelvin - 1.0 / t2) / (1.0 / t1 - 1.0 / t2), 0.0, 1.0))


@dataclass(frozen=True)
class DngWhite:
    """The as-shot white the matrix was computed for (for diagnostics and tests)."""

    xy: tuple[float, float]
    kelvin: float
    weight: float
    """Weight of calibration illuminant 1's matrices."""


def dng_camera_to_working(colour: DngColour) -> tuple[Matrix, DngWhite]:
    """White-balanced camera RGB → linear Rec.2020 (D65), per the DNG specification.

    "White-balanced" means camera RGB divided by the as-shot neutral, as LibRaw delivers it
    with ``use_camera_wb``. The result maps (1, 1, 1) to (1, 1, 1).
    """
    analogue = (
        np.diag(colour.analogue_balance) if colour.analogue_balance is not None else np.eye(3)
    )

    def xyz_to_camera(weight: float) -> Matrix:
        calibration = (
            _blend(colour.camera_calibrations, weight) if colour.camera_calibrations else np.eye(3)
        )
        return analogue @ calibration @ _blend(colour.colour_matrices, weight)

    def white_for(weight: float) -> tuple[NDArray[np.float64], tuple[float, float]]:
        """Camera neutral and xy of the as-shot white, given the blend weight."""
        if colour.as_shot_neutral is not None:
            neutral = colour.as_shot_neutral
            return neutral, xyz_to_xy(np.linalg.solve(xyz_to_camera(weight), neutral))
        xy = colour.as_shot_white_xy or D65
        return xyz_to_camera(weight) @ xy_to_xyz(xy), xy

    kelvins = colour.illuminant_kelvin
    two = len(colour.colour_matrices) == 2 and None not in kelvins and kelvins[0] != kelvins[1]
    if two:
        illuminants = (float(kelvins[0]), float(kelvins[1]))  # type: ignore[arg-type]
        # h(w) = weight_for(cct(white(w))) - w falls as w rises; find its zero.
        low, high = 0.0, 1.0
        for _ in range(_BISECTION_STEPS):
            middle = 0.5 * (low + high)
            if _weight_for(xy_to_cct(white_for(middle)[1]), illuminants) > middle:
                low = middle
            else:
                high = middle
        weight = 0.5 * (low + high)
    else:
        weight = 1.0
    neutral, white_xy = white_for(weight)

    if colour.forward_matrices:
        calibration = (
            _blend(colour.camera_calibrations, weight) if colour.camera_calibrations else np.eye(3)
        )
        reference_neutral = np.linalg.solve(analogue @ calibration, neutral)
        camera_to_d50 = (
            _blend(colour.forward_matrices, weight)
            @ np.diag(1.0 / reference_neutral)
            @ np.linalg.inv(analogue @ calibration)
        )
        to_d65 = bradford_matrix(D50, D65) @ camera_to_d50
    else:
        to_d65 = bradford_matrix(white_xy, D65) @ np.linalg.inv(xyz_to_camera(weight))
    matrix = XYZ_TO_REC2020 @ to_d65 @ np.diag(neutral)
    matrix /= float(np.mean(matrix @ np.ones(3)))
    return matrix, DngWhite(xy=white_xy, kelvin=xy_to_cct(white_xy), weight=weight)
