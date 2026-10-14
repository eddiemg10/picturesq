"""Display transform: scene-linear working space -> display-linear Rec.709/sRGB primaries."""

import numpy as np
from numpy.typing import NDArray

from picturesq.colour.spaces import REC2020_TO_REC709, apply_matrix

FloatArray = NDArray[np.float32]


def display_transform(image: FloatArray, out: FloatArray | None = None) -> FloatArray:
    """Map a scene-linear image (linear Rec.2020) to display-linear Rec.709 in [0, 1].

    v0 temporary version: Rec.2020 to Rec.709 primaries, then a hard clip to [0, 1], with
    no highlight roll-off, so anything brighter than 1.0 clips to white. Issue #17 (AgX,
    implemented by the project owner) replaces the body of this function, keeping the
    signature. The result still needs ``srgb_encode`` before 8-bit export.

    Pass ``out`` (which may be ``image`` itself) to avoid allocating a new array.
    """
    result = apply_matrix(image, REC2020_TO_REC709, out=out)
    return np.clip(result, 0.0, 1.0, out=result)
