"""Oklab (Björn Ottosson, 2020): a perceptual colour space for chroma operations.

``L`` is lightness (0.18 grey ≈ 0.565, white = 1), ``a`` green-red and ``b`` blue-yellow.
Distances and blurs in ``a``/``b`` change colour without changing lightness, which is why
chroma noise reduction works here. Input is linear XYZ-based; we convert from the working
space (linear Rec.2020) via XYZ. The cube root is signed, so negative (out-of-gamut) values
and values above 1 round-trip.
"""

import numpy as np

from picturesq.colour.spaces import (
    REC709_TO_XYZ,
    REC2020_TO_XYZ,
    XYZ_TO_REC709,
    XYZ_TO_REC2020,
    Matrix,
    apply_matrix,
)
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


_REC709_TO_LMS = XYZ_TO_LMS @ REC709_TO_XYZ
_LMS_TO_REC709 = XYZ_TO_REC709 @ np.linalg.inv(XYZ_TO_LMS)


def rec709_to_oklab(image: FloatArray, out: FloatArray | None = None) -> FloatArray:
    """Linear Rec.709 (display-linear sRGB primaries) → Oklab. ``out`` may be ``image``."""
    out = apply_matrix(image, _REC709_TO_LMS, out=out)
    np.cbrt(out, out=out)
    return apply_matrix(out, LMS_TO_OKLAB, out=out)


def oklab_to_rec709(image: FloatArray, out: FloatArray | None = None) -> FloatArray:
    """Oklab → linear Rec.709. Inverse of :func:`rec709_to_oklab`; ``out`` may be ``image``."""
    out = apply_matrix(image, _OKLAB_TO_LMS, out=out)
    np.power(out, 3, out=out)
    return apply_matrix(out, _LMS_TO_REC709, out=out)


GAMUT_FIT_STEPS = 20
"""Bisection steps of :func:`fit_gamut_oklab`: chroma is found to within 2⁻²⁰ of its value."""
GAMUT_TOLERANCE = 1e-4
"""How far outside [0, 1] a channel may be and still count as inside (float32 round trips)."""


def fit_gamut_oklab(lab: FloatArray) -> FloatArray:
    """Oklab pixels (N, 3) → linear Rec.709 in [0, 1], reducing chroma at constant hue.

    Pixels already inside the gamut convert unchanged. For the others, lightness is clamped
    to [0, 1] and chroma is scaled down (a and b together, so Oklab hue and lightness are
    kept) to the largest value that fits: the hue-preserving gamut mapping of Ottosson's
    Oklab gamut clipping and ACES 2.0 (which uses a different perceptual space). Pulling a
    pixel toward grey along a line in *linear* RGB instead bends blues toward purple.
    """
    rgb = oklab_to_rec709(lab)
    outside = ((rgb < -GAMUT_TOLERANCE) | (rgb > 1.0 + GAMUT_TOLERANCE)).any(axis=-1)
    if not outside.any():
        return np.clip(rgb, 0.0, 1.0, out=rgb)
    pixels = lab[outside].copy()
    np.clip(pixels[:, 0], 0.0, 1.0, out=pixels[:, 0])
    low = np.zeros(len(pixels), dtype=lab.dtype)
    high = np.ones(len(pixels), dtype=lab.dtype)
    trial = np.empty_like(pixels)
    for _ in range(GAMUT_FIT_STEPS):
        scale = 0.5 * (low + high)
        trial[:, 0] = pixels[:, 0]
        np.multiply(pixels[:, 1:], scale[:, None], out=trial[:, 1:])
        candidate = oklab_to_rec709(trial)
        # The same tolerance as the inside test: a pixel just outside it then fits to where
        # one just inside is clipped (no jump that float rounding could flip).
        fits = ((candidate >= -GAMUT_TOLERANCE) & (candidate <= 1.0 + GAMUT_TOLERANCE)).all(axis=-1)
        low = np.where(fits, scale, low)
        high = np.where(fits, high, scale)
    pixels[:, 1:] *= low[:, None]
    rgb[outside] = oklab_to_rec709(pixels)
    return np.clip(rgb, 0.0, 1.0, out=rgb)
