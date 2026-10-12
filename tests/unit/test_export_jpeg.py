"""Tests for 8-bit quantisation and JPEG writing."""

import io
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray
from PIL import Image, ImageCms

from picturesq.export import to_8bit, write_jpeg


def test_to_8bit_values_and_dtype() -> None:
    out = to_8bit(np.array([[[0.0, 0.5, 1.0]]], dtype=np.float32))
    assert out.dtype == np.uint8
    assert out.tolist() == [[[0, 128, 255]]]


def test_to_8bit_clips_out_of_range() -> None:
    out = to_8bit(np.array([[[-0.2, 1.5, 0.0]]], dtype=np.float32))
    assert out.tolist() == [[[0, 255, 0]]]


def _noise(height: int = 64, width: int = 64) -> NDArray[np.uint8]:
    return np.random.default_rng(0).integers(0, 256, (height, width, 3), dtype=np.uint8)


def test_round_trip_and_icc_profile(tmp_path: Path) -> None:
    path = tmp_path / "a.jpg"
    write_jpeg(_noise(32, 48), path, quality=90)
    with Image.open(path) as image:
        assert image.size == (48, 32)
        assert image.mode == "RGB"
        icc = image.info["icc_profile"]
    profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
    assert "sRGB" in ImageCms.getProfileDescription(profile)


def test_higher_quality_gives_larger_file(tmp_path: Path) -> None:
    low, high = tmp_path / "low.jpg", tmp_path / "high.jpg"
    write_jpeg(_noise(), low, quality=30)
    write_jpeg(_noise(), high, quality=95)
    assert high.stat().st_size > low.stat().st_size


def test_atomic_write_leaves_no_temp_files_and_creates_parents(tmp_path: Path) -> None:
    path = tmp_path / "exports" / "deep" / "a.jpg"
    write_jpeg(_noise(16, 16), path, quality=80)
    assert [p.name for p in path.parent.iterdir()] == ["a.jpg"]


def test_failed_write_leaves_no_partial_file(tmp_path: Path) -> None:
    path = tmp_path / "a.jpg"
    bad = np.zeros((4, 4, 2), dtype=np.uint8)  # LA, JPEG cannot save it
    with pytest.raises(Exception):  # noqa: B017
        write_jpeg(bad, path, quality=80)
    assert list(tmp_path.iterdir()) == []
