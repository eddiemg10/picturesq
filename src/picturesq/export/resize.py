"""Resize an image to a long-edge size, in float32 (no 8-bit quantisation)."""

from functools import partial

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from picturesq import parallel

FloatArray = NDArray[np.float32]


def resize_to_long_edge(image: FloatArray, long_edge: int | None) -> FloatArray:
    """Downscale so the long side is ``long_edge`` pixels; never upscale.

    Returns the same object (no copy) when ``long_edge`` is None or the image is already
    no larger. The short side is ``round()``-ed and at least 1.

    Do this in scene-linear, before the display transform: averaging pixels is only
    physically right on linear light.

    Resampling is Lanczos (sharp), with **anti-ringing**: each output value is clamped to
    the range of a box-averaged (area) copy over its 3x3 neighbourhood. Lanczos's negative
    lobes overshoot next to edges; on scene-linear data an edge can be a 100:1 jump (a sun
    glint on dark water), and the undershoot then exceeds the dark side's own value, giving
    negative pixels that the display transform shows as black speckle (#55). The box copy
    has no negative lobes, so its local range bounds what the output can plausibly be;
    ordinary edges, where Lanczos stays inside that range, keep its sharpness.
    """
    if long_edge is None:
        return image
    height, width = image.shape[:2]
    long_side = max(height, width)
    if long_side <= long_edge:
        return image
    scale = long_edge / long_side
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    out = np.empty((size[1], size[0], image.shape[2]), dtype=np.float32)

    def resize_channel(channel: int) -> None:  # Pillow releases the GIL while resizing
        plane = Image.fromarray(np.ascontiguousarray(image[..., channel]))
        sharp = np.asarray(plane.resize(size, Image.Resampling.LANCZOS))
        area = np.asarray(plane.resize(size, Image.Resampling.BOX))
        np.clip(
            sharp,
            _neighbourhood(area, np.minimum),
            _neighbourhood(area, np.maximum),
            out=out[..., channel],
        )

    parallel.run(partial(resize_channel, channel) for channel in range(image.shape[2]))
    return out


def _neighbourhood(plane: FloatArray, combine: np.ufunc) -> FloatArray:
    """``combine`` (min or max) of each pixel's 3x3 neighbourhood, edges repeated."""
    padded = np.pad(plane, 1, mode="edge")
    height, width = plane.shape
    result = padded[1 : height + 1, 1 : width + 1].copy()
    for dy in range(3):
        for dx in range(3):
            combine(result, padded[dy : dy + height, dx : dx + width], out=result)
    return result
