"""Swap the EXIF block of a JPEG without touching anything else in the file.

A JPEG is a run of marker segments, then the scan: the entropy-coded image data, from the
start-of-scan marker to the end. Rewriting metadata means replacing one segment (APP1,
``Exif``); every other byte, the image data above all, is copied as it is, so nothing is
re-encoded and nothing about the picture can change.
"""

import struct
from typing import Final

_SOI: Final = b"\xff\xd8"
_SOS: Final = 0xDA
_APP0: Final = 0xE0
_APP1: Final = 0xE1
_EXIF_PREFIX: Final = b"Exif\x00\x00"
_MAX_PAYLOAD: Final = 0xFFFF - 2
# Markers with no length field: TEM, RSTn, SOI, EOI.
_STANDALONE: Final = frozenset({0x01, *range(0xD0, 0xDA)})


class JpegError(ValueError):
    """The bytes are not a JPEG this module can walk."""


def _segments(jpeg: bytes) -> tuple[list[tuple[int, int, int]], int]:
    """``([(marker, start, end)], scan_start)``: the segments before the scan (``start`` at the
    0xFF, ``end`` after the last byte) and where the scan begins."""
    if not jpeg.startswith(_SOI):
        raise JpegError("not a JPEG (no start-of-image marker)")
    found: list[tuple[int, int, int]] = []
    position = len(_SOI)
    while True:
        if position + 2 > len(jpeg):
            raise JpegError("the JPEG ends before its image data")
        if jpeg[position] != 0xFF:
            raise JpegError(f"expected a marker at byte {position}")
        marker = jpeg[position + 1]
        if marker == 0xFF:  # fill byte before a marker
            position += 1
            continue
        if marker == _SOS:
            return found, position
        if marker in _STANDALONE:
            found.append((marker, position, position + 2))
            position += 2
            continue
        if position + 4 > len(jpeg):
            raise JpegError("truncated JPEG segment")
        (length,) = struct.unpack(">H", jpeg[position + 2 : position + 4])
        end = position + 2 + length
        if length < 2 or end > len(jpeg):
            raise JpegError(f"bad segment length at byte {position}")
        found.append((marker, position, end))
        position = end


def _is_exif(jpeg: bytes, marker: int, start: int) -> bool:
    return marker == _APP1 and jpeg[start + 4 : start + 4 + len(_EXIF_PREFIX)] == _EXIF_PREFIX


def read_exif(jpeg: bytes) -> bytes | None:
    """The EXIF APP1 payload (``Exif\\0\\0`` + TIFF block) of ``jpeg``, or None."""
    segments, _ = _segments(jpeg)
    for marker, start, end in segments:
        if _is_exif(jpeg, marker, start):
            return jpeg[start + 4 : end]
    return None


def replace_exif(jpeg: bytes, exif: bytes) -> bytes:
    """``jpeg`` with its EXIF block replaced by ``exif`` (an APP1 payload, as ``export_exif``
    makes). A JPEG without one gets it after the JFIF header (or first). Only the EXIF
    segment differs; all other bytes are unchanged."""
    if len(exif) > _MAX_PAYLOAD:
        raise JpegError("the EXIF block is too large for one JPEG segment")
    segments, _ = _segments(jpeg)
    new = b"\xff" + bytes([_APP1]) + struct.pack(">H", len(exif) + 2) + exif
    out = bytearray(_SOI)
    placed = False
    cursor = len(_SOI)
    for marker, start, end in segments:
        if cursor != start:  # fill bytes between segments are kept
            out += jpeg[cursor:start]
        cursor = end
        if _is_exif(jpeg, marker, start):
            if not placed:
                out += new
                placed = True
            continue  # a second EXIF block is dropped
        out += jpeg[start:end]
        if marker == _APP0 and not placed and start == len(_SOI):
            out += new
            placed = True
    if not placed:
        out[len(_SOI) : len(_SOI)] = new
    out += jpeg[cursor:]
    return bytes(out)
