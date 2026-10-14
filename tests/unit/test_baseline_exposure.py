from __future__ import annotations

from pathlib import Path

import numpy as np
import tifffile

from picturesq.config.project import DecodeConfig
from picturesq.decode import read_baseline_exposure

_PIXELS = np.zeros((4, 4), dtype=np.uint16)


def test_junk_file_gives_zero(tmp_path: Path) -> None:
    junk = tmp_path / "junk.raf"
    junk.write_bytes(b"FUJIFILMCCD-RAW" + b"\x00" * 200)
    assert read_baseline_exposure(junk) == 0.0


def test_tiff_without_tag_gives_zero(tmp_path: Path) -> None:
    path = tmp_path / "plain.tif"
    tifffile.imwrite(path, _PIXELS)
    assert read_baseline_exposure(path) == 0.0


def test_tiff_with_tag_gives_value(tmp_path: Path) -> None:
    path = tmp_path / "tagged.tif"
    # 50730 = BaselineExposure, type 10 = SRATIONAL
    tifffile.imwrite(path, _PIXELS, extratags=[(50730, 10, 1, (3, 2), True)])
    assert read_baseline_exposure(path) == 1.5


def test_negative_value(tmp_path: Path) -> None:
    path = tmp_path / "negative.tif"
    tifffile.imwrite(path, _PIXELS, extratags=[(50730, 10, 1, (-1, 2), True)])
    assert read_baseline_exposure(path) == -0.5


def test_config_default_applies_baseline_exposure() -> None:
    assert DecodeConfig().baseline_exposure is True
    assert DecodeConfig(baseline_exposure=False).baseline_exposure is False
