"""Write an 8-bit sRGB JPEG with an embedded ICC profile, atomically."""

import functools
import io
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageCms

from picturesq.atomic import atomic_write


@functools.cache
def srgb_icc_profile() -> bytes:
    """Pillow's built-in sRGB profile (description "sRGB built-in"), built once."""
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def write_jpeg(
    pixels: NDArray[np.uint8], path: Path, *, quality: int, exif: bytes | None = None
) -> None:
    """Save ``pixels`` (HxWx3 uint8, sRGB-encoded) as a JPEG at ``path``.

    Chroma subsampling is off (4:4:4): outputs are archive-quality, so we keep full colour
    resolution and accept larger files. Huffman tables are optimised. The sRGB profile is
    always embedded. ``exif`` is an EXIF block (``export_exif``). The file is written
    atomically, so an interrupted export never leaves a truncated JPEG.
    """
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(
        buffer,
        format="JPEG",
        quality=quality,
        subsampling=0,
        optimize=True,
        icc_profile=srgb_icc_profile(),
        exif=exif if exif is not None else b"",
    )
    atomic_write(path, buffer.getvalue())
