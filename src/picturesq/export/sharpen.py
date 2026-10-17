"""Output sharpening: an unsharp mask on lightness, at the output's final size."""

import numpy as np
from numpy.typing import NDArray

from picturesq.colour.filters import gaussian_blur_plane, gaussian_radius
from picturesq.config import SharpenConfig

# Rec.709 luma weights, applied to sRGB-encoded values (Y').
_LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def sharpened_rows(
    encoded: NDArray[np.float32], config: SharpenConfig, top: int, bottom: int
) -> NDArray[np.float32]:
    """Rows ``top:bottom`` of sRGB-encoded ``encoded`` (HxWx3), sharpened, as a new array.

    ``detail = luma - blur(luma)`` is added to all three channels, so edges get crisper
    without colour fringes. Working on encoded values (not linear light) makes the halo
    on the dark side of an edge as visible as on the bright side, as the eye expects.
    Done at the output's size, after resizing, so the radius means the same on every output.

    ``encoded`` is only read, so blocks of rows can be sharpened in parallel. Each block
    blurs its rows plus the blur's radius above and below, so the result is the same as
    blurring the whole image at once.
    """
    rows = encoded[top:bottom]
    if config.amount <= 0.0:
        return rows.copy()
    radius = gaussian_radius(config.radius)
    first, last = max(0, top - radius), min(encoded.shape[0], bottom + radius)
    luma = encoded[first:last] @ _LUMA
    inner = slice(top - first, bottom - first)
    detail = luma[inner] - gaussian_blur_plane(luma, config.radius)[inner]
    del luma
    np.multiply(detail, np.float32(config.amount), out=detail)
    return np.add(rows, detail[..., None])


def sharpen(encoded: NDArray[np.float32], config: SharpenConfig) -> NDArray[np.float32]:
    """Sharpen sRGB-encoded ``encoded`` (HxWx3) in place and return it (see ``sharpened_rows``)."""
    encoded[...] = sharpened_rows(encoded, config, 0, encoded.shape[0])
    return encoded
