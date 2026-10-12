"""Stage 1, decode: original RAW -> scene-linear image in the working space (rawpy), proxies."""

from picturesq.decode.discovery import RAW_EXTENSIONS, find_originals

__all__ = ["RAW_EXTENSIONS", "find_originals"]
