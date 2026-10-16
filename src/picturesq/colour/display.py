"""Display transform: scene-linear working space -> display-linear Rec.709/sRGB primaries."""

import numpy as np
from numpy.typing import NDArray

from picturesq.colour.agx import AgxCurve, agx
from picturesq.config import DisplayTransformConfig

FloatArray = NDArray[np.float32]


def display_transform(
    image: FloatArray,
    config: DisplayTransformConfig | None = None,
    out: FloatArray | None = None,
) -> FloatArray:
    """Map a scene-linear image (linear Rec.2020) to display-linear Rec.709 in [0, 1].

    The AgX-style transform (``colour/agx.py``) with ``config`` (default settings when
    None). The result still needs ``srgb_encode`` before 8-bit export.

    Pass ``out`` (which may be ``image`` itself) to avoid allocating a new array.
    """
    curve = AgxCurve.from_config(config or DisplayTransformConfig())
    return agx(image, curve, out=out)
