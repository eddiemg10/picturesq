"""Stage 1, decode: original RAW -> scene-linear image in the working space (rawpy), proxies."""

from picturesq.decode.exposure import read_baseline_exposure
from picturesq.decode.raw import DecodeError, decode_original

__all__ = ["DecodeError", "decode_original", "read_baseline_exposure"]
