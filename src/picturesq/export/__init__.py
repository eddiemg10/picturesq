"""Stage 4, export: encode, resize and write each enabled output, with EXIF and sidecar."""

from picturesq.export.encode import to_8bit
from picturesq.export.exif import export_exif
from picturesq.export.jpeg import srgb_icc_profile, write_jpeg
from picturesq.export.jpeg_segments import JpegError, read_exif, replace_exif
from picturesq.export.resize import resize_to_long_edge
from picturesq.export.sidecar import (
    SIDECAR_SUFFIX,
    metadata_document,
    sha256_file,
    sidecar_document,
    sidecar_path,
    write_sidecar,
)

__all__ = [
    "SIDECAR_SUFFIX",
    "JpegError",
    "export_exif",
    "metadata_document",
    "read_exif",
    "replace_exif",
    "resize_to_long_edge",
    "sha256_file",
    "sidecar_document",
    "sidecar_path",
    "srgb_icc_profile",
    "to_8bit",
    "write_jpeg",
    "write_sidecar",
]
