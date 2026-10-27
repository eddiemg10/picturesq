"""Rewrite the capture dates of exports already on disk, without re-rendering.

Only the JPEG's EXIF segment is replaced (``picturesq.export.jpeg_segments``): the image
data is copied byte for byte. The sidecar's ``metadata`` section is updated to match. The
camera's own time is taken from the sidecar (the exported dates may already be corrected),
or from the JPEG for an export made before sidecars recorded it.
"""

import io
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image
from PIL.ExifTags import Base

from picturesq.atomic import atomic_write
from picturesq.config import ProjectConfig
from picturesq.decode.exif import capture_from_exif
from picturesq.export import (
    JpegError,
    metadata_document,
    read_exif,
    replace_exif,
    sidecar_path,
    write_sidecar,
)
from picturesq.export.exif import export_exif
from picturesq.export.sidecar import SIDECAR_VERSION
from picturesq.metadata import (
    CaptureTime,
    CaptureTimeError,
    camera_capture_time,
    photo_capture_time,
    with_capture_time,
)
from picturesq.pipeline.export import SOFTWARE


@dataclass
class RewriteResult:
    """What happened to one exported JPEG."""

    path: Path
    photo: str | None = None
    capture_time: CaptureTime | None = None
    changed: bool = False
    error: str | None = None


def _sidecar(path: Path) -> dict[str, Any] | None:
    try:
        document = json.loads(sidecar_path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return document if isinstance(document, dict) else None


def _recorded_camera_time(document: Mapping[str, Any]) -> tuple[bool, datetime | None]:
    """``(recorded, time)``: whether the sidecar records the camera's time, and what it is."""
    metadata = document.get("metadata")
    if not isinstance(metadata, dict) or "camera_time" not in metadata:
        return False, None
    text = metadata["camera_time"]
    try:
        return True, None if text is None else datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return False, None


def rewrite_export(
    path: Path, config: ProjectConfig, originals_by_stem: Mapping[str, str]
) -> RewriteResult:
    """Rewrite the dates in the JPEG at ``path`` (and its sidecar) to match ``config``.

    ``originals_by_stem`` maps an original's stem to its file name, to find the photo of an
    export whose sidecar is missing. Failures are recorded in the result, not raised.
    """
    result = RewriteResult(path)
    document = _sidecar(path)
    original = document.get("original") if document else None
    name = original.get("name") if isinstance(original, dict) else None
    result.photo = name if isinstance(name, str) else originals_by_stem.get(path.stem)
    if result.photo is None:
        result.error = "no sidecar and no original of that name in the project"
        return result
    try:
        jpeg = path.read_bytes()
        payload = read_exif(jpeg)
        exif = Image.Exif()
        if payload is not None:
            exif.load(payload)
        capture = capture_from_exif(exif)
        recorded, camera = _recorded_camera_time(document or {})
        if not recorded:
            camera = camera_capture_time(capture)  # never corrected: the JPEG has the camera's
        when = photo_capture_time(config, result.photo, camera)
        result.capture_time = when
        with Image.open(io.BytesIO(jpeg)) as image:
            width, height = image.size
        software = exif.get(Base.Software)
        updated = export_exif(
            with_capture_time(capture, when, force=True),
            width=width,
            height=height,
            software=software if isinstance(software, str) else SOFTWARE,
        )
        if payload != updated:
            atomic_write(path, replace_exif(jpeg, updated))
            result.changed = True
        if document is not None:
            before = document.get("metadata")
            after = metadata_document(when)
            if before != after or document.get("sidecar_version") != SIDECAR_VERSION:
                document["metadata"] = after
                document["sidecar_version"] = SIDECAR_VERSION
                write_sidecar(sidecar_path(path), document)
                result.changed = True
    except (OSError, JpegError, CaptureTimeError, ValueError) as error:
        result.error = str(error)
    return result


def rewrite_exports(
    exports_dir: Path,
    outputs: Sequence[str],
    config: ProjectConfig,
    originals: Sequence[Path],
) -> list[RewriteResult]:
    """Rewrite every JPEG in ``<exports_dir>/<output>/`` for each of ``outputs``."""
    by_stem = {original.stem: original.name for original in originals}
    results: list[RewriteResult] = []
    for output in outputs:
        for path in sorted((exports_dir / output).glob("*.jpg")):
            results.append(rewrite_export(path, config, by_stem))
    return results
