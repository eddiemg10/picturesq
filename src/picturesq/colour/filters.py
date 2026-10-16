"""Spatial filters on float32 planes (HxW) or images (HxWxC). Pure numpy."""

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float32]


def box_blur(image: FloatArray, radius: int, axis: int) -> FloatArray:
    """Mean over a window of ``2 * radius + 1`` along ``axis``; edges repeat the border pixel."""
    if radius <= 0:
        return image.copy()
    pad = [(0, 0)] * image.ndim
    pad[axis] = (radius + 1, radius)
    padded = np.pad(image.astype(np.float64), pad, mode="edge")
    sums = np.cumsum(padded, axis=axis)
    size = image.shape[axis]
    upper = np.take(sums, np.arange(2 * radius + 1, 2 * radius + 1 + size), axis=axis)
    lower = np.take(sums, np.arange(0, size), axis=axis)
    return ((upper - lower) / (2 * radius + 1)).astype(np.float32)


def gaussian_blur(image: FloatArray, sigma: float) -> FloatArray:
    """Approximate Gaussian blur over the first two axes: three box passes per axis.

    Three box blurs of radius ``r`` have variance ``3 * ((2r + 1)**2 - 1) / 12``; ``r`` is
    chosen so this is closest to ``sigma**2``. Good for smoothing (noise reduction, unsharp
    masks), not for exact optics.
    """
    radius = max(0, round((np.sqrt(4.0 * sigma**2 + 1.0) - 1.0) / 2.0))
    out = image
    for axis in (0, 1):
        for _ in range(3):
            out = box_blur(out, radius, axis)
    return out if out is not image else image.copy()


def upsample_rows(small: FloatArray, height: int, width: int, top: int, bottom: int) -> FloatArray:
    """Rows ``top:bottom`` of ``small`` (hxwxC) bilinearly resized to ``height``x``width``.

    Pixel centres are aligned, as in Pillow's resize, so a block of rows can be produced
    without materialising the whole upsampled image.
    """
    h, w = small.shape[:2]
    ys = (np.arange(top, bottom) + 0.5) * (h / height) - 0.5
    xs = (np.arange(width) + 0.5) * (w / width) - 0.5
    y0 = np.clip(np.floor(ys).astype(np.intp), 0, h - 1)
    x0 = np.clip(np.floor(xs).astype(np.intp), 0, w - 1)
    y1, x1 = np.minimum(y0 + 1, h - 1), np.minimum(x0 + 1, w - 1)
    fy = np.clip(ys - y0, 0.0, 1.0).astype(np.float32)[:, None, None]
    fx = np.clip(xs - x0, 0.0, 1.0).astype(np.float32)[None, :, None]
    rows = small[y0] * (1.0 - fy) + small[y1] * fy
    return rows[:, x0] * (1.0 - fx) + rows[:, x1] * fx


def gaussian_blur_plane(plane: FloatArray, sigma: float) -> FloatArray:
    """Exact Gaussian blur of a 2-D float32 plane by separable convolution (small sigmas).

    Kernel radius ``ceil(3 * sigma)``; edges repeat the border pixel. Memory: two planes.
    """
    radius = max(1, int(np.ceil(3.0 * sigma)))
    taps = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sigma) ** 2)
    taps = (taps / taps.sum()).astype(np.float32)
    out = plane
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (radius, radius)
        padded = np.pad(out, pad, mode="edge")
        size = plane.shape[axis]
        result = np.zeros_like(plane)
        for offset, weight in enumerate(taps):
            window = (
                padded[offset : offset + size] if axis == 0 else padded[:, offset : offset + size]
            )
            result += weight * window
        out = result
    return out


def _recursive_pass(lines: FloatArray, weights: FloatArray) -> None:
    """One left-to-right and one right-to-left recursive pass along axis 1, in place.

    ``weights[:, i]`` is how much of pixel ``i - 1`` carries into pixel ``i`` (0 stops the
    smoothing there). The loop runs over columns, vectorised across lines.
    """
    for i in range(1, lines.shape[1]):
        lines[:, i] += weights[:, i] * (lines[:, i - 1] - lines[:, i])
    for i in range(lines.shape[1] - 2, -1, -1):
        lines[:, i] += weights[:, i + 1] * (lines[:, i + 1] - lines[:, i])


def edge_aware_blur(
    plane: FloatArray, sigma: float, edge: float, iterations: int = 3
) -> FloatArray:
    """Smooth a 2-D plane without blurring across steps much larger than ``edge``.

    The domain transform recursive filter (Gastal & Oliveira, 2011): spatial scale ``sigma``
    pixels, range scale ``edge`` (in the plane's units). Between two neighbours that differ
    by ``d``, the distance the filter sees is stretched by ``1 + sigma / edge * d``, so a
    big step works like a wall. Python loops over rows and columns: meant for small planes
    (about 0.15 s at 512 x 384).
    """
    ratio = np.float32(sigma / edge)
    stretch_x = np.ones_like(plane)
    stretch_x[:, 1:] += ratio * np.abs(np.diff(plane, axis=1))
    stretch_y = np.ones_like(plane)
    stretch_y[1:, :] += ratio * np.abs(np.diff(plane, axis=0))
    stretch_y = np.ascontiguousarray(stretch_y.T)
    out = plane.astype(np.float32, copy=True)
    for k in range(iterations):
        # Each iteration halves the spatial scale so the total matches `sigma` (the paper's
        # schedule).
        sigma_k = sigma * np.sqrt(3.0) * 2.0 ** (iterations - k - 1) / np.sqrt(4.0**iterations - 1)
        carry = np.float32(np.exp(-np.sqrt(2.0) / sigma_k))
        _recursive_pass(out, carry**stretch_x)
        transposed = np.ascontiguousarray(out.T)
        _recursive_pass(transposed, carry**stretch_y)
        out = np.ascontiguousarray(transposed.T)
    return out
