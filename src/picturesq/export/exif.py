"""Build the EXIF block written into each exported JPEG.

We serialise the block ourselves rather than through Pillow, which picks each tag's type
from its value: an exposure compensation of 0 becomes an *unsigned* rational, an ISO an
int16 or int32 depending on its size. Readers that follow the EXIF specification (ExifTool
validation, photo libraries) expect the specification's type for each tag, so every tag
we write has its type declared below.
"""

import struct
from collections.abc import Mapping, Sequence
from fractions import Fraction
from numbers import Rational
from typing import Any, Final

from PIL.ExifTags import IFD, Base

from picturesq.decode.exif import CaptureExif

_ASCII: Final = 2
_SHORT: Final = 3
_LONG: Final = 4
_RATIONAL: Final = 5
_UNDEFINED: Final = 7
_SRATIONAL: Final = 10

# Types from the EXIF 2.32 specification (CIPA DC-008), tables 4-8.
TAG_TYPES: Final[dict[int, int]] = {
    Base.Make: _ASCII,
    Base.Model: _ASCII,
    Base.Orientation: _SHORT,
    Base.Software: _ASCII,
    Base.DateTime: _ASCII,
    Base.Artist: _ASCII,
    Base.YCbCrPositioning: _SHORT,
    Base.Copyright: _ASCII,
    IFD.Exif: _LONG,
    Base.ExposureTime: _RATIONAL,
    Base.FNumber: _RATIONAL,
    Base.ExposureProgram: _SHORT,
    Base.ISOSpeedRatings: _SHORT,
    Base.SensitivityType: _SHORT,
    Base.RecommendedExposureIndex: _LONG,
    Base.ExifVersion: _UNDEFINED,
    Base.DateTimeOriginal: _ASCII,
    Base.DateTimeDigitized: _ASCII,
    Base.OffsetTime: _ASCII,
    Base.OffsetTimeOriginal: _ASCII,
    Base.OffsetTimeDigitized: _ASCII,
    Base.ComponentsConfiguration: _UNDEFINED,
    Base.ShutterSpeedValue: _SRATIONAL,
    Base.ApertureValue: _RATIONAL,
    Base.BrightnessValue: _SRATIONAL,
    Base.ExposureBiasValue: _SRATIONAL,
    Base.MaxApertureValue: _RATIONAL,
    Base.SubjectDistance: _RATIONAL,
    Base.MeteringMode: _SHORT,
    Base.LightSource: _SHORT,
    Base.Flash: _SHORT,
    Base.FocalLength: _RATIONAL,
    Base.SubsecTime: _ASCII,
    Base.SubsecTimeOriginal: _ASCII,
    Base.SubsecTimeDigitized: _ASCII,
    Base.ColorSpace: _SHORT,
    Base.ExifImageWidth: _LONG,
    Base.ExifImageHeight: _LONG,
    Base.ExposureMode: _SHORT,
    Base.WhiteBalance: _SHORT,
    Base.DigitalZoomRatio: _RATIONAL,
    Base.FocalLengthIn35mmFilm: _SHORT,
    Base.SceneCaptureType: _SHORT,
    Base.LensSpecification: _RATIONAL,
    Base.LensMake: _ASCII,
    Base.LensModel: _ASCII,
}

_HEADER: Final = b"Exif\x00\x00"
_TIFF_HEADER: Final = b"II*\x00" + struct.pack("<I", 8)
_UPRIGHT: Final = 1
_CENTRED: Final = 1  # YCbCrPositioning; required in a JPEG's IFD0
_SRGB: Final = 1
_EXIF_VERSION: Final = b"0232"
_YCBCR_COMPONENTS: Final = b"\x01\x02\x03\x00"  # ComponentsConfiguration; required in a JPEG
_MAX_SHORT: Final = 0xFFFF
_MAX_DENOMINATOR: Final = 1_000_000
_INT32: Final = 2**31 - 1


def _rational(value: Any, *, signed: bool) -> tuple[int, int]:
    if isinstance(value, Rational):
        if value.denominator == 0:
            return 0, 0  # EXIF's "unknown" (LensSpecification's missing apertures)
        fraction = Fraction(int(value.numerator), int(value.denominator))
    else:
        fraction = Fraction(float(value)).limit_denominator(_MAX_DENOMINATOR)
    numerator, denominator = fraction.numerator, fraction.denominator
    if not signed and numerator < 0:
        raise ValueError("negative value for an unsigned rational")
    while abs(numerator) > _INT32 or denominator > (_INT32 if signed else 2 * _INT32 + 1):
        numerator, denominator = numerator // 2, denominator // 2 or 1
    return numerator, denominator


def _encode(tag: int, value: Any) -> tuple[int, int, bytes]:
    """``(type, count, data)`` for one tag; raises ValueError/TypeError on a value that
    doesn't fit its type."""
    kind = TAG_TYPES[tag]
    values: Sequence[Any] = value if isinstance(value, tuple | list) else (value,)
    if kind == _ASCII:
        data = str(value).encode("utf-8") + b"\x00"
        return kind, len(data), data
    if kind == _UNDEFINED:
        return kind, len(value), bytes(value)
    if kind == _SHORT:
        # An ISO above 65535 is stored as 65535 (RecommendedExposureIndex holds the value).
        shorts = [min(int(v), _MAX_SHORT) for v in values]
        return kind, len(shorts), struct.pack(f"<{len(shorts)}H", *shorts)
    if kind == _LONG:
        return kind, len(values), struct.pack(f"<{len(values)}I", *(int(v) for v in values))
    signed = kind == _SRATIONAL
    pairs = [part for v in values for part in _rational(v, signed=signed)]
    return kind, len(values), struct.pack(f"<{len(pairs)}{'i' if signed else 'I'}", *pairs)


def _directory(tags: Mapping[int, Any], offset: int) -> bytes:
    """One IFD at file ``offset`` (from the TIFF header), entries then their out-of-line data.

    Tags whose value doesn't fit their type are left out: metadata is best effort.
    """
    encoded: list[tuple[int, int, int, bytes]] = []
    for tag in sorted(tags):
        try:
            encoded.append((tag, *_encode(tag, tags[tag])))
        except (ValueError, TypeError, OverflowError, struct.error, ZeroDivisionError):
            continue
    entries = bytearray(struct.pack("<H", len(encoded)))
    data = bytearray()
    data_offset = offset + 2 + 12 * len(encoded) + 4
    for tag, kind, count, payload in encoded:
        if len(payload) <= 4:
            field = payload.ljust(4, b"\x00")
        else:
            field = struct.pack("<I", data_offset + len(data))
            data += payload + b"\x00" * (len(payload) % 2)  # word-aligned
        entries += struct.pack("<HHI", tag, kind, count) + field
    entries += struct.pack("<I", 0)  # no next IFD
    return bytes(entries + data)


def export_exif(capture: CaptureExif, *, width: int, height: int, software: str) -> bytes:
    """EXIF for an export of ``width`` x ``height`` pixels: the original's capture EXIF, plus
    what describes the export itself.

    Orientation is always upright (decode already rotated the pixels), the colour space is
    sRGB and the pixel dimensions are the export's. ``software`` names the program that made it.
    The result is the JPEG APP1 payload (``Exif\\0\\0`` + a little-endian TIFF block).
    """
    exif_tags: dict[int, Any] = {
        **capture.exif,
        Base.ExifVersion: _EXIF_VERSION,
        Base.ComponentsConfiguration: _YCBCR_COMPONENTS,
        Base.ColorSpace: _SRGB,
        Base.ExifImageWidth: width,
        Base.ExifImageHeight: height,
    }
    image_tags: dict[int, Any] = {
        **capture.image,
        Base.Orientation: _UPRIGHT,
        Base.Software: software,
        Base.YCbCrPositioning: _CENTRED,
        IFD.Exif: 0,  # placeholder: the pointer's value is known once IFD0's size is
    }
    image_directory = _directory(image_tags, len(_TIFF_HEADER))
    exif_offset = len(_TIFF_HEADER) + len(image_directory)
    image_tags[IFD.Exif] = exif_offset
    image_directory = _directory(image_tags, len(_TIFF_HEADER))  # same size, real pointer
    return _HEADER + _TIFF_HEADER + image_directory + _directory(exif_tags, exif_offset)
