"""RGB colour spaces and the 3x3 matrices between them (linear values only).

A colour space here is three primaries and a white point, as CIE 1931 xy chromaticities.
Matrices are *derived* from those numbers (ADR-0007), so white maps to white exactly; we
don't use the 4-decimal matrix printed in the sRGB standard.

The transfer function is separate (``colour/transfer.py``): apply these matrices to
scene-linear data only, never to sRGB-encoded values.
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from picturesq.colour.transfer import FloatArray

Matrix = NDArray[np.float64]

D65 = (0.3127, 0.3290)
"""CIE standard daylight white point (xy). Used by sRGB, Rec.709 and Rec.2020."""


@dataclass(frozen=True)
class RgbSpace:
    """Primaries and white point of a linear RGB space."""

    name: str
    red: tuple[float, float]
    green: tuple[float, float]
    blue: tuple[float, float]
    white: tuple[float, float]


REC2020 = RgbSpace("rec2020", (0.708, 0.292), (0.170, 0.797), (0.131, 0.046), D65)
"""ITU-R BT.2020 primaries: the working space."""
REC709 = RgbSpace("rec709", (0.640, 0.330), (0.300, 0.600), (0.150, 0.060), D65)
"""ITU-R BT.709 primaries, shared by sRGB: the export space."""


def _xy_to_xyz(xy: tuple[float, float]) -> NDArray[np.float64]:
    """Chromaticity → XYZ with luminance Y = 1."""
    x, y = xy
    return np.array([x / y, 1.0, (1.0 - x - y) / y])


def rgb_to_xyz_matrix(space: RgbSpace) -> Matrix:
    """The matrix taking linear RGB in ``space`` to CIE XYZ (white → Y = 1).

    Columns are the primaries' XYZ, each scaled so that R = G = B = 1 sums to the white
    point.
    """
    primaries = np.column_stack([_xy_to_xyz(p) for p in (space.red, space.green, space.blue)])
    scale = np.linalg.solve(primaries, _xy_to_xyz(space.white))
    return primaries * scale


def xyz_to_rgb_matrix(space: RgbSpace) -> Matrix:
    """Inverse of :func:`rgb_to_xyz_matrix`."""
    return np.linalg.inv(rgb_to_xyz_matrix(space))


def rgb_to_rgb_matrix(source: RgbSpace, target: RgbSpace) -> Matrix:
    """The matrix taking linear RGB in ``source`` to linear RGB in ``target``, via XYZ.

    Both spaces must share a white point; a different white needs chromatic adaptation,
    which picturesq doesn't need yet.
    """
    if not np.allclose(source.white, target.white):
        raise ValueError(
            f"{source.name} and {target.name} have different white points; "
            "chromatic adaptation is not implemented"
        )
    return xyz_to_rgb_matrix(target) @ rgb_to_xyz_matrix(source)


REC2020_TO_XYZ = rgb_to_xyz_matrix(REC2020)
XYZ_TO_REC2020 = xyz_to_rgb_matrix(REC2020)
REC709_TO_XYZ = rgb_to_xyz_matrix(REC709)
XYZ_TO_REC709 = xyz_to_rgb_matrix(REC709)
REC2020_TO_REC709 = rgb_to_rgb_matrix(REC2020, REC709)
REC709_TO_REC2020 = rgb_to_rgb_matrix(REC709, REC2020)


def apply_matrix(image: FloatArray, matrix: Matrix, out: FloatArray | None = None) -> FloatArray:
    """Multiply every pixel of ``image`` (..., 3) by ``matrix``: ``out = matrix @ pixel``.

    Keeps the image dtype. Values aren't clipped: colours outside the target gamut come out
    with negative channels, which the display transform deals with.
    """
    if image.shape[-1] != 3:
        raise ValueError(f"expected 3 channels in the last axis, got shape {image.shape}")
    # numpy buffers overlapping operands, so `out` may be `image`.
    return np.matmul(image, matrix.T.astype(image.dtype), out=out)
