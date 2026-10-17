"""Write an 8-bit sRGB JPEG with an embedded ICC profile, atomically."""

import functools
import io
import struct
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageCms

from picturesq.atomic import atomic_write

_ICC_DATE = slice(24, 36)
"""The profile header's creation date and time: six big-endian 16-bit numbers."""
_ICC_FIXED_DATE = struct.pack(">6H", 2000, 1, 1, 0, 0, 0)


@functools.cache
def srgb_icc_profile() -> bytes:
    """Pillow's built-in sRGB profile (description "sRGB built-in"), built once.

    LittleCMS stamps the profile with the time it was built, so two runs (or two workers)
    would embed different bytes; the date is fixed instead, so the same originals, config
    and version give byte-identical JPEGs. The profile has no ID checksum over it (its
    profile ID is zero).
    """
    profile = bytearray(ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
    profile[_ICC_DATE] = _ICC_FIXED_DATE
    return bytes(profile)


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
