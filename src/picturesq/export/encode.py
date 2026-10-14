"""Quantise a transfer-encoded image to 8 bits."""

import numpy as np
from numpy.typing import NDArray


def to_8bit(encoded: NDArray[np.float32]) -> NDArray[np.uint8]:
    """Clip to [0, 1], scale by 255 and round to nearest (ties to even, numpy's default).

    The input must already be transfer-encoded (``srgb_encode``). 0.5 gives 128
    (127.5 ties to the even neighbour).
    """
    scaled = np.clip(encoded, 0.0, 1.0) * np.float32(255.0)
    return np.rint(scaled).astype(np.uint8)
