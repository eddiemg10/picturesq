"""Stage 1, decode: original RAW -> scene-linear image in the working space (rawpy), proxies."""

from picturesq.decode.raw import DecodeError, decode_original

__all__ = ["DecodeError", "decode_original"]
