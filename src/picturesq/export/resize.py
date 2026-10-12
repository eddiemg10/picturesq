"""Resize an image to a long-edge size, in float32 (no 8-bit quantisation)."""

import numpy as np
from numpy.typing import NDArray
from PIL import Image

FloatArray = NDArray[np.float32]


def resize_to_long_edge(image: FloatArray, long_edge: int | None) -> FloatArray:
    """Downscale so the long side is ``long_edge`` pixels; never upscale.

    Returns the same object (no copy) when ``long_edge`` is None or the image is already
    no larger. The short side is ``round()``-ed and at least 1. Resampling is Lanczos, per
    channel in Pillow's float32 mode "F".

    Do this in scene-linear, before the display transform: averaging pixels is only
    physically right on linear light. Lanczos can overshoot slightly (including below 0)
    next to hard edges. The result is deliberately not clamped here; later steps clip
    (``to_8bit``) and ``srgb_encode`` must tolerate small negatives.
    """
    if long_edge is None:
        return image
    height, width = image.shape[:2]
    long_side = max(height, width)
    if long_side <= long_edge:
        return image
    scale = long_edge / long_side
    new_width = max(1, round(width * scale))
    new_height = max(1, round(height * scale))
    out = np.empty((new_height, new_width, image.shape[2]), dtype=np.float32)
    for channel in range(image.shape[2]):
        plane = Image.fromarray(np.ascontiguousarray(image[..., channel]))
        resized = plane.resize((new_width, new_height), Image.Resampling.LANCZOS)
        out[..., channel] = np.asarray(resized)
    return out
