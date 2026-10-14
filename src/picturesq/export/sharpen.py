"""Output sharpening: an unsharp mask on lightness, at the output's final size."""

import numpy as np
from numpy.typing import NDArray

from picturesq.colour.filters import gaussian_blur_plane
from picturesq.config import SharpenConfig

# Rec.709 luma weights, applied to sRGB-encoded values (Y').
_LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def sharpen(encoded: NDArray[np.float32], config: SharpenConfig) -> NDArray[np.float32]:
    """Sharpen sRGB-encoded ``encoded`` (HxWx3) in place and return it.

    ``detail = luma - blur(luma)`` is added to all three channels, so edges get crisper
    without colour fringes. Working on encoded values (not linear light) makes the halo
    on the dark side of an edge as visible as on the bright side, as the eye expects.
    Done at the output's size, after resizing, so the radius means the same on every output.
    """
    if config.amount <= 0.0:
        return encoded
    luma = encoded @ _LUMA
    detail = luma - gaussian_blur_plane(luma, config.radius)
    del luma
    np.multiply(detail, np.float32(config.amount), out=detail)
    np.add(encoded, detail[..., None], out=encoded)
    return encoded
