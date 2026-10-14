"""Oklab (Björn Ottosson, 2020): a perceptual colour space for chroma operations.

``L`` is lightness (0.18 grey ≈ 0.565, white = 1), ``a`` green-red and ``b`` blue-yellow.
Distances and blurs in ``a``/``b`` change colour without changing lightness, which is why
chroma noise reduction works here. Input is linear XYZ-based; we convert from the working
space (linear Rec.2020) via XYZ. The cube root is signed, so negative (out-of-gamut) values
and values above 1 round-trip.
"""

import numpy as np

from picturesq.colour.spaces import REC2020_TO_XYZ, XYZ_TO_REC2020, Matrix, apply_matrix
from picturesq.colour.transfer import FloatArray

# Published matrices (Ottosson, "A perceptual color space for image processing").
XYZ_TO_LMS: Matrix = np.array(
    [
        [0.8189330101, 0.3618667424, -0.1288597137],
        [0.0329845436, 0.9293118715, 0.0361456387],
        [0.0482003018, 0.2643662691, 0.6338517070],
    ]
)
LMS_TO_OKLAB: Matrix = np.array(
    [
        [0.2104542553, 0.7936177850, -0.0040720468],
        [1.9779984951, -2.4285922050, 0.4505937099],
        [0.0259040371, 0.7827717662, -0.8086757660],
    ]
)
_REC2020_TO_LMS = XYZ_TO_LMS @ REC2020_TO_XYZ
_LMS_TO_REC2020 = XYZ_TO_REC2020 @ np.linalg.inv(XYZ_TO_LMS)
_OKLAB_TO_LMS = np.linalg.inv(LMS_TO_OKLAB)


def rec2020_to_oklab(image: FloatArray, out: FloatArray | None = None) -> FloatArray:
    """Linear Rec.2020 → Oklab. ``out`` may be ``image``."""
    out = apply_matrix(image, _REC2020_TO_LMS, out=out)
    np.cbrt(out, out=out)
    return apply_matrix(out, LMS_TO_OKLAB, out=out)


def oklab_to_rec2020(image: FloatArray, out: FloatArray | None = None) -> FloatArray:
    """Oklab → linear Rec.2020. Inverse of :func:`rec2020_to_oklab`; ``out`` may be ``image``."""
    out = apply_matrix(image, _OKLAB_TO_LMS, out=out)
    np.power(out, 3, out=out)
    return apply_matrix(out, _LMS_TO_REC2020, out=out)
