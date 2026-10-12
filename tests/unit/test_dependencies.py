"""Smoke test: the M1 runtime dependencies import and their native parts load."""

import numpy as np
import rawpy._rawpy as libraw
from PIL import Image, features


def test_rawpy_links_libraw() -> None:
    assert libraw.libraw_version >= (0, 21)


def test_pillow_has_jpeg_and_icc() -> None:
    assert features.check("jpg")
    assert features.check("littlecms2")


def test_imports() -> None:
    import pydantic  # noqa: F401
    import tifffile  # noqa: F401
    import yaml  # noqa: F401

    assert Image.fromarray(np.zeros((2, 2, 3), dtype=np.uint8)).size == (2, 2)
