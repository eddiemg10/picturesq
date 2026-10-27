"""Read the capture EXIF of an original: when, with what camera and lens, at what settings.

Only an allowlist is kept. The rest of an original's metadata describes the RAW file itself
(sensor size, DNG colour tags, the camera's own JPEG processing: contrast, sharpness) or is
private (serial numbers, location), and would be wrong or unwanted on an export.

TIFF-based originals (DNG, ARW, NEF, CR2, PEF) are read directly. Others (RAF, CR3, ORF,
RW2) fall back to the EXIF of the camera JPEG embedded in the original. Metadata is best
effort: an original whose EXIF can't be read gives an empty result, never an error.
"""

from __future__ import annotations

import io
import struct
import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import rawpy
from PIL import Image, UnidentifiedImageError
from PIL.ExifTags import IFD, Base
from rawpy._rawpy import LibRawError, ThumbFormat

IMAGE_TAGS: Final = frozenset({Base.Make, Base.Model, Base.DateTime, Base.Artist, Base.Copyright})
"""Kept from the image directory (IFD0)."""

EXIF_TAGS: Final = frozenset(
    {
        # Capture time, with sub-seconds and time zone.
        Base.DateTimeOriginal,
        Base.DateTimeDigitized,
        Base.SubsecTime,
        Base.SubsecTimeOriginal,
        Base.SubsecTimeDigitized,
        Base.OffsetTime,
        Base.OffsetTimeOriginal,
        Base.OffsetTimeDigitized,
        # Exposure.
        Base.ExposureTime,
        Base.FNumber,
        Base.ExposureProgram,
        Base.ISOSpeedRatings,
        Base.SensitivityType,
        Base.RecommendedExposureIndex,
        Base.ShutterSpeedValue,
        Base.ApertureValue,
        Base.BrightnessValue,
        Base.ExposureBiasValue,
        Base.MaxApertureValue,
        Base.ExposureMode,
        Base.MeteringMode,
        Base.LightSource,
        Base.Flash,
        Base.WhiteBalance,
        Base.SceneCaptureType,
        Base.SubjectDistance,
        # Lens.
        Base.FocalLength,
        Base.FocalLengthIn35mmFilm,
        Base.DigitalZoomRatio,
        Base.LensSpecification,
        Base.LensMake,
        Base.LensModel,
    }
)
"""Kept from the EXIF directory."""

_TIFF_MAGIC: Final = (b"II*\x00", b"MM\x00*")
# What a malformed or truncated EXIF block can raise from Pillow's parser.
_PARSE_ERRORS: Final = (OSError, ValueError, SyntaxError, struct.error, KeyError, IndexError)


@dataclass(frozen=True)
class CaptureExif:
    """Allowlisted EXIF values of one original, by tag id; values as Pillow reads them."""

    image: Mapping[int, Any] = field(default_factory=dict)
    exif: Mapping[int, Any] = field(default_factory=dict)


def _clean(value: Any) -> Any:
    """Strip the NUL and space padding cameras leave in fixed-width strings ('PENTAX   ')."""
    if isinstance(value, str):
        return value.split("\x00", 1)[0].strip()
    return value


def _keep(directory: Mapping[int, Any], allowed: frozenset[int]) -> dict[int, Any]:
    kept = {tag: _clean(value) for tag, value in directory.items() if tag in allowed}
    return {tag: value for tag, value in kept.items() if value != "" and value is not None}


def capture_from_exif(exif: Image.Exif) -> CaptureExif:
    """The allowlisted values of an EXIF block Pillow has parsed."""
    return CaptureExif(image=_keep(exif, IMAGE_TAGS), exif=_keep(exif.get_ifd(IFD.Exif), EXIF_TAGS))


def _from_tiff(path: Path) -> CaptureExif:
    with path.open("rb") as file:
        exif = Image.Exif()
        exif.load_from_fp(file)
        # The EXIF directory is read lazily, from the open file.
        return capture_from_exif(exif)


def _from_camera_jpeg(path: Path) -> CaptureExif:
    with rawpy.imread(str(path)) as raw:
        thumb = raw.extract_thumb()
    if thumb.format != ThumbFormat.JPEG:
        return CaptureExif()
    with Image.open(io.BytesIO(thumb.data)) as image:
        return capture_from_exif(image.getexif())


def read_capture_exif(path: Path) -> CaptureExif:
    """The allowlisted EXIF of the original at ``path`` (empty if it has none or can't be read)."""
    try:
        with path.open("rb") as file:
            magic = file.read(4)
        # Pillow warns about corrupt EXIF; metadata is best effort, so that's not news.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            if magic in _TIFF_MAGIC:
                capture = _from_tiff(path)
                if capture.exif:
                    return capture
            return _from_camera_jpeg(path)
    except (*_PARSE_ERRORS, LibRawError, UnidentifiedImageError):
        return CaptureExif()
