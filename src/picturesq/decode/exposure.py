"""Read the DNG ``BaselineExposure`` tag from an original (file IO, so it lives in ``decode/``)."""

from __future__ import annotations

from pathlib import Path
from typing import Final

import tifffile

# DNG tag 50730: how many stops (EV) a renderer should brighten the raw data. Cameras such as the
# DJI Pocket 4 deliberately underexpose the raw to protect highlights and record the difference.
BASELINE_EXPOSURE_TAG: Final = 50730


def read_baseline_exposure(path: Path) -> float:
    """Return the ``BaselineExposure`` of the original at ``path`` in stops (EV).

    Returns 0.0 when the file is not TIFF-based (e.g. Fujifilm RAF), cannot be parsed as TIFF, or
    has no such tag in its first image file directory (IFD0).
    """
    try:
        with tifffile.TiffFile(path) as tiff:
            tag = tiff.pages.first.tags.get(BASELINE_EXPOSURE_TAG)
            value = None if tag is None else tag.value
    except (tifffile.TiffFileError, ValueError, IndexError):
        return 0.0
    if value is None:
        return 0.0
    if isinstance(value, tuple | list):
        if len(value) == 2 and value[1] != 0:  # SRATIONAL as (numerator, denominator)
            return float(value[0]) / float(value[1])
        if len(value) == 1:
            return float(value[0])
        return 0.0
    return float(value)
