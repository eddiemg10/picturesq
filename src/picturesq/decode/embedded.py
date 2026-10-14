"""Read the camera's own JPEG embedded in an original (file IO, so it lives in ``decode/``)."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import rawpy
from numpy.typing import NDArray
from PIL import Image, ImageOps
from rawpy._rawpy import LibRawNoThumbnailError, LibRawUnsupportedThumbnailError, ThumbFormat


def camera_jpeg(path: Path) -> NDArray[np.uint8] | None:
    """The JPEG (or bitmap) embedded in the original, upright, or None if there is none."""
    try:
        with rawpy.imread(str(path)) as raw:
            thumb = raw.extract_thumb()
    except (LibRawNoThumbnailError, LibRawUnsupportedThumbnailError):
        return None
    if thumb.format == ThumbFormat.JPEG:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(thumb.data)))  # EXIF orientation
        return np.asarray(image.convert("RGB"), dtype=np.uint8)
    if thumb.format == ThumbFormat.BITMAP:
        return np.asarray(thumb.data, dtype=np.uint8)
    return None
