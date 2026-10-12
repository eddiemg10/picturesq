"""Decode an original (RAW file) into a scene-linear image in the working space.

Output: float32 ``HxWx3``, linear light, Rec.2020 primaries, D65 white, C-contiguous. The image is
oriented upright (LibRaw applies the file's orientation tag; we leave ``user_flip`` at its default).
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import numpy as np
import rawpy
from numpy.typing import NDArray

# rawpy re-exports these at runtime, but its type stubs only declare them in rawpy._rawpy.
from rawpy._rawpy import ColorSpace, DemosaicAlgorithm, HighlightMode, LibRawError

from picturesq.config.project import DecodeConfig

# Keyed by the Literal values of ``DecodeConfig.demosaic``. LibRaw ignores this choice for X-Trans
# (Fuji) sensors and always uses its own X-Trans demosaic.
DEMOSAIC_ALGORITHMS: Final[dict[str, DemosaicAlgorithm]] = {
    "linear": DemosaicAlgorithm.LINEAR,
    "vng": DemosaicAlgorithm.VNG,
    "ppg": DemosaicAlgorithm.PPG,
    "ahd": DemosaicAlgorithm.AHD,
    "dcb": DemosaicAlgorithm.DCB,
    "dht": DemosaicAlgorithm.DHT,
    "aahd": DemosaicAlgorithm.AAHD,
}

# Keyed by the Literal values of ``DecodeConfig.highlight_mode``.
HIGHLIGHT_MODES: Final[dict[str, HighlightMode]] = {
    "clip": HighlightMode.Clip,
    "ignore": HighlightMode.Ignore,
    "blend": HighlightMode.Blend,
    "reconstruct": HighlightMode.ReconstructDefault,
}

_UINT16_MAX: Final = 65535.0


class DecodeError(Exception):
    """An original could not be read or decoded (unreadable, corrupt or unsupported)."""


def decode_original(
    path: Path, config: DecodeConfig, *, half_size: bool = False
) -> NDArray[np.float32]:
    """Decode the original at ``path`` to a scene-linear float32 ``HxWx3`` image.

    ``half_size`` skips demosaicing (each 2x2 block becomes one pixel): much faster, for proxies
    and tests.

    Colour space: LibRaw converts camera RGB straight to linear Rec.2020 (``output_color``).
    We measured LibRaw's XYZ output too: it is D65-referred, and our derived XYZ to Rec.2020
    matrix reproduces LibRaw's Rec.2020 within 0.2 %, so the white point is the same (D65) in
    both. But the XYZ route stores Z as a 16-bit value capped at 1.0 while D65 white has Z = 1.089,
    so bright neutrals lose blue (about 8 % on a near-white pixel), which tints highlights.
    Direct Rec.2020 keeps the neutral axis neutral. Its cost: colours outside the Rec.2020 gamut
    are clipped to 0 by LibRaw before we see them.

    No brightness scaling is applied here (no DNG BaselineExposure, no auto-brightness): exposure
    is the job of the normalise stage.
    """
    try:
        with rawpy.imread(str(path)) as raw:
            rgb16 = raw.postprocess(
                demosaic_algorithm=DEMOSAIC_ALGORITHMS[config.demosaic],
                highlight_mode=HIGHLIGHT_MODES[config.highlight_mode],
                half_size=half_size,
                use_camera_wb=True,
                no_auto_bright=True,
                gamma=(1, 1),
                output_bps=16,
                output_color=ColorSpace.Rec2020,
            )
    except (LibRawError, OSError) as err:
        raise DecodeError(f"cannot decode {path.name}: {err}") from err

    image = np.empty(rgb16.shape, dtype=np.float32)
    np.multiply(rgb16, np.float32(1.0 / _UINT16_MAX), out=image, dtype=np.float32)
    del rgb16
    return image
