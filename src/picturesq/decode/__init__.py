"""Stage 1, decode: original RAW -> scene-linear image in the working space (rawpy), proxies."""

from picturesq.decode.discovery import RAW_EXTENSIONS, find_originals
from picturesq.decode.exif import CaptureExif, read_capture_exif
from picturesq.decode.exposure import read_baseline_exposure
from picturesq.decode.info import PhotoInfo, read_photo_info
from picturesq.decode.raw import DecodeError, decode_original, read_pixel_count

__all__ = [
    "RAW_EXTENSIONS",
    "CaptureExif",
    "DecodeError",
    "PhotoInfo",
    "decode_original",
    "find_originals",
    "read_baseline_exposure",
    "read_capture_exif",
    "read_photo_info",
    "read_pixel_count",
]
