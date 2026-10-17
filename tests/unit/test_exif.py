"""Capture EXIF: read from an original (allowlisted, cleaned) and written into an export."""

import struct
from pathlib import Path

import numpy as np
from PIL import Image
from PIL.ExifTags import IFD, Base
from PIL.TiffImagePlugin import IFDRational

from picturesq.decode import CaptureExif, read_capture_exif
from picturesq.decode.exif import EXIF_TAGS, IMAGE_TAGS
from picturesq.export import export_exif, write_jpeg
from picturesq.export.exif import TAG_TYPES


def _tiff_original(path: Path) -> Path:
    """A TIFF-based 'original' (like DNG/ARW) with capture EXIF and tags we must drop."""
    exif = Image.Exif()
    exif[Base.Make] = "PENTAX     "
    exif[Base.Model] = "Q7\x00\x00\x00"
    exif[Base.Orientation] = 6
    exif[Base.ImageDescription] = "raw strip"
    directory = exif.get_ifd(IFD.Exif)
    directory[Base.DateTimeOriginal] = "2017:10:01 22:30:27"
    directory[Base.ExposureTime] = IFDRational(1, 250)
    directory[Base.FNumber] = IFDRational(19, 10)
    directory[Base.ExposureBiasValue] = IFDRational(-2, 3)
    directory[Base.ISOSpeedRatings] = 800
    directory[Base.LensModel] = "01 STANDARD PRIME"
    directory[Base.BodySerialNumber] = "4777130"
    directory[Base.MakerNote] = b"\x01\x02proprietary"
    directory[Base.Contrast] = 2
    Image.new("RGB", (8, 8)).save(path, format="TIFF", exif=exif.tobytes())
    return path


def test_reads_allowlisted_tags_from_a_tiff_original(tmp_path: Path) -> None:
    capture = read_capture_exif(_tiff_original(tmp_path / "a.dng"))
    assert capture.image == {Base.Make: "PENTAX", Base.Model: "Q7"}
    assert capture.exif[Base.DateTimeOriginal] == "2017:10:01 22:30:27"
    assert float(capture.exif[Base.ExposureTime]) == 1 / 250
    assert capture.exif[Base.ISOSpeedRatings] == 800
    assert capture.exif[Base.LensModel] == "01 STANDARD PRIME"
    for dropped in (Base.BodySerialNumber, Base.MakerNote, Base.Contrast):
        assert dropped not in capture.exif


def test_unreadable_original_gives_empty_exif(tmp_path: Path) -> None:
    path = tmp_path / "a.dng"
    path.write_bytes(b"not really a raw")
    assert read_capture_exif(path) == CaptureExif()


def test_truncated_tiff_gives_empty_exif(tmp_path: Path) -> None:
    path = _tiff_original(tmp_path / "a.dng")
    path.write_bytes(path.read_bytes()[:12])
    assert read_capture_exif(path) == CaptureExif()


def _written(capture: CaptureExif, tmp_path: Path) -> Image.Exif:
    pixels = np.zeros((20, 30, 3), dtype=np.uint8)
    path = tmp_path / "out.jpg"
    exif = export_exif(capture, width=30, height=20, software="picturesq 9.9")
    write_jpeg(pixels, path, quality=90, exif=exif)
    with Image.open(path) as image:
        return image.getexif()


def test_export_carries_capture_exif(tmp_path: Path) -> None:
    capture = read_capture_exif(_tiff_original(tmp_path / "a.dng"))
    exif = _written(capture, tmp_path)
    assert exif[Base.Make] == "PENTAX"
    assert exif[Base.Software] == "picturesq 9.9"
    directory = exif.get_ifd(IFD.Exif)
    assert directory[Base.DateTimeOriginal] == "2017:10:01 22:30:27"
    assert float(directory[Base.FNumber]) == 1.9
    assert float(directory[Base.ExposureBiasValue]) == -2 / 3  # signed rational survives
    assert directory[Base.LensModel] == "01 STANDARD PRIME"


def test_export_describes_itself_not_the_original(tmp_path: Path) -> None:
    capture = read_capture_exif(_tiff_original(tmp_path / "a.dng"))
    exif = _written(capture, tmp_path)
    assert exif[Base.Orientation] == 1  # pixels are already upright
    assert Base.ImageDescription not in exif
    directory = exif.get_ifd(IFD.Exif)
    assert directory[Base.ColorSpace] == 1
    assert (directory[Base.ExifImageWidth], directory[Base.ExifImageHeight]) == (30, 20)


def test_export_without_capture_exif_is_still_valid(tmp_path: Path) -> None:
    exif = _written(CaptureExif(), tmp_path)
    assert exif[Base.Orientation] == 1
    assert Base.Make not in exif


def test_export_exif_is_deterministic() -> None:
    capture = CaptureExif(image={Base.Make: "DJI"}, exif={Base.ISOSpeedRatings: 100})
    first = export_exif(capture, width=4, height=3, software="s")
    assert first == export_exif(capture, width=4, height=3, software="s")
    parsed = Image.Exif()
    parsed.load(first)
    assert parsed[Base.Make] == "DJI"


def test_every_copied_tag_has_a_declared_type() -> None:
    assert TAG_TYPES.keys() >= IMAGE_TAGS
    assert TAG_TYPES.keys() >= EXIF_TAGS


def _tiff_entries(block: bytes, directory_offset: int) -> dict[int, tuple[int, int, int]]:
    """``{tag: (type, count, value or offset)}`` of the IFD at ``directory_offset``."""
    tiff = block[len(b"Exif\x00\x00") :]
    (count,) = struct.unpack_from("<H", tiff, directory_offset)
    return {
        tag: (kind, n, field)
        for tag, kind, n, field in (
            struct.unpack_from("<HHII", tiff, directory_offset + 2 + 12 * index)
            for index in range(count)
        )
    }


def test_tags_are_written_with_the_specification_types() -> None:
    capture = CaptureExif(
        exif={
            Base.ExposureBiasValue: IFDRational(0, 1),  # zero, yet a signed rational
            Base.ISOSpeedRatings: 102400,  # above a SHORT: stored as 65535
            Base.RecommendedExposureIndex: 400,  # small, yet a LONG
            Base.LensSpecification: (
                IFDRational(85, 10),
                IFDRational(85, 10),
                1.9,
                IFDRational(0, 0),
            ),
        }
    )
    block = export_exif(capture, width=4, height=3, software="s")
    image = _tiff_entries(block, 8)
    exif = _tiff_entries(block, image[IFD.Exif][2])
    assert exif[Base.ExposureBiasValue][:2] == (10, 1)  # SRATIONAL
    assert exif[Base.RecommendedExposureIndex][:2] == (4, 1)  # LONG
    assert exif[Base.LensSpecification][:2] == (5, 4)  # 4 RATIONALs
    assert Base.ComponentsConfiguration in exif
    assert image[Base.YCbCrPositioning][:2] == (3, 1)
    parsed = Image.Exif()
    parsed.load(block)
    directory = parsed.get_ifd(IFD.Exif)
    assert directory[Base.ISOSpeedRatings] == 65535
    assert float(directory[Base.LensSpecification][2]) == 1.9


def test_a_value_that_does_not_fit_its_type_is_skipped() -> None:
    capture = CaptureExif(exif={Base.FNumber: -2.0, Base.ISOSpeedRatings: 100})
    parsed = Image.Exif()
    parsed.load(export_exif(capture, width=4, height=3, software="s"))
    directory = parsed.get_ifd(IFD.Exif)
    assert Base.FNumber not in directory
    assert directory[Base.ISOSpeedRatings] == 100
