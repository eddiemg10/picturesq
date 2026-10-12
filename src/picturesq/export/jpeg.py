"""Write an 8-bit sRGB JPEG with an embedded ICC profile, atomically."""

import functools
import os
import tempfile
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageCms


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
    always embedded. Parent folders are created. The file is written to a temp file in the
    same folder and renamed, so an interrupted export never leaves a truncated JPEG.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.fromarray(pixels)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as file:
            image.save(
                file,
                format="JPEG",
                quality=quality,
                subsampling=0,
                optimize=True,
                icc_profile=srgb_icc_profile(),
                exif=exif if exif is not None else b"",
            )
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
