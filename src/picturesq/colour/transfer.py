"""Transfer functions: the curves between scene-linear and encoded values.

- sRGB (IEC 61966-2-1): the piecewise curve used by JPEGs and most screens. It is a
  straight line near black and a 1/2.4 power above it, *not* a pure 2.2 gamma.
- EV: log2 relative to mid grey, the unit picturesq uses for exposure (one stop = x2).

Every function takes a float array of any shape and returns an array of the same dtype.
Pass ``out`` (which may be the input itself) to avoid allocating a new array.
"""

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.floating]

# IEC 61966-2-1 constants.
SRGB_LINEAR_BREAK = 0.0031308
"""Scene-linear value where the sRGB curve switches from the straight line to the power."""
SRGB_ENCODED_BREAK = 0.04045
"""The same point on the encoded side."""
_SRGB_SLOPE = 12.92
_SRGB_EXPONENT = 2.4
_SRGB_OFFSET = 0.055

MIDDLE_GREY = 0.18
"""Scene-linear mid grey: 0 EV."""
EV_FLOOR = 2.0**-20
"""Linear values at or below this (including zero and negatives) are clamped before log2."""


def _out_like(image: FloatArray, out: FloatArray | None) -> FloatArray:
    if out is None:
        return np.empty_like(image)
    if out.shape != image.shape:
        raise ValueError(f"out has shape {out.shape}, expected {image.shape}")
    return out


def srgb_encode(image: FloatArray, out: FloatArray | None = None) -> FloatArray:
    """Scene-linear → sRGB-encoded.

    Values outside 0-1 are extended, not clipped: negatives (out-of-gamut colours) follow
    the straight segment and values above 1 follow the power curve, so the result decodes
    back exactly. Clipping is the caller's decision (export does it at 8-bit).
    """
    out = _out_like(image, out)
    low = image <= SRGB_LINEAR_BREAK
    # Each step reads and writes the same elements, so `out` may be `image`.
    np.multiply(image, _SRGB_SLOPE, out=out, where=low)
    high = np.logical_not(low, out=low)
    np.power(image, 1.0 / _SRGB_EXPONENT, out=out, where=high)
    np.multiply(out, 1.0 + _SRGB_OFFSET, out=out, where=high)
    np.subtract(out, _SRGB_OFFSET, out=out, where=high)
    return out


def srgb_decode(image: FloatArray, out: FloatArray | None = None) -> FloatArray:
    """sRGB-encoded → scene-linear. Inverse of :func:`srgb_encode`, extended the same way."""
    out = _out_like(image, out)
    low = image <= SRGB_ENCODED_BREAK
    np.divide(image, _SRGB_SLOPE, out=out, where=low)
    high = np.logical_not(low, out=low)
    np.add(image, _SRGB_OFFSET, out=out, where=high)
    np.divide(out, 1.0 + _SRGB_OFFSET, out=out, where=high)
    np.power(out, _SRGB_EXPONENT, out=out, where=high)
    return out


def linear_to_ev(
    image: FloatArray,
    middle_grey: float = MIDDLE_GREY,
    floor: float = EV_FLOOR,
    out: FloatArray | None = None,
) -> FloatArray:
    """Scene-linear → EV relative to ``middle_grey`` (``log2(value / middle_grey)``).

    0.18 → 0 EV, 0.36 → +1 EV, 0.09 → -1 EV. Values ≤ ``floor`` map to the floor's EV
    instead of -inf/NaN.
    """
    out = _out_like(image, out)
    np.maximum(image, floor, out=out)
    np.divide(out, middle_grey, out=out)
    np.log2(out, out=out)
    return out


def ev_to_linear(
    image: FloatArray,
    middle_grey: float = MIDDLE_GREY,
    out: FloatArray | None = None,
) -> FloatArray:
    """EV relative to ``middle_grey`` → scene-linear (``middle_grey * 2**ev``)."""
    out = _out_like(image, out)
    np.exp2(image, out=out)
    np.multiply(out, middle_grey, out=out)
    return out
