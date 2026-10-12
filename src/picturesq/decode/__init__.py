"""Stage 1, decode: original RAW -> scene-linear image in the working space (rawpy), proxies."""

from picturesq.decode.discovery import RAW_EXTENSIONS, find_originals
from picturesq.decode.exposure import read_baseline_exposure
from picturesq.decode.raw import DecodeError, decode_original

__all__ = [
    "RAW_EXTENSIONS",
    "DecodeError",
    "decode_original",
    "find_originals",
    "read_baseline_exposure",
]
