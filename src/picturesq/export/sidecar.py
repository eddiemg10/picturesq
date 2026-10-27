"""The sidecar written next to each export: everything needed to reproduce it.

``<output>/<stem>.picturesq.json`` records the picturesq version, the original (name and
SHA-256, so a changed or swapped original is detectable) and the config that rendered this
export: the decode, normalise and grade sections, this photo's overrides (``photos``: only
this photo's entry, keyed by the original's name, or ``{}`` without overrides) and this
output's settings. The recorded ``config`` is itself a valid config that renders this photo
the same way. It holds no timestamps or paths, so the same original + config + version
always gives the same bytes.

It also records the photo's resolved ``look`` (name, intensity, every parameter's value and
the look file's SHA-256), so a changed look file is detectable.

It records the photo's capture time under ``metadata``: ``camera_time`` (what the original
says), ``capture_time`` (what the export carries) and ``time_zone``, as ISO 8601 text or null.
The ``metadata`` config is not part of ``config``: it changes no pixel, and
``picturesq metadata apply`` rewrites it without re-rendering.

Sidecar versions: 1 had no ``config.photos``; 2 adds it; 3 adds ``look``; 4 adds ``metadata``.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Final

from picturesq.atomic import atomic_write
from picturesq.config import ProjectConfig
from picturesq.config.project import NO_OVERRIDES
from picturesq.metadata import CaptureTime
from picturesq.photo import ResolvedLook

SIDECAR_SUFFIX: Final = ".picturesq.json"
SIDECAR_VERSION: Final = 4
_CHUNK: Final = 1 << 20


def sha256_file(path: Path) -> str:
    """Hex SHA-256 of a file, read in chunks (originals are tens of MB)."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def sidecar_document(
    *,
    version: str,
    original: Path,
    original_sha256: str,
    output: str,
    config: ProjectConfig,
    look: ResolvedLook | None = None,
    capture_time: CaptureTime | None = None,
) -> dict[str, Any]:
    """The sidecar of ``original``'s export to ``output``, as a JSON-ready dict.

    ``look`` is the photo's resolved look: its name, intensity, every parameter's value and
    the look file's SHA-256 (null for no look). ``capture_time`` is recorded under ``metadata``.
    """
    rendered = config.model_dump(mode="json", include={"decode", "normalise", "grade"})
    overrides = config.photo(original.name)
    # Metadata overrides change no pixel: they are recorded under "metadata", not here.
    rendering = overrides.model_copy(update={"metadata": NO_OVERRIDES.metadata})
    photos = (
        {}
        if rendering == NO_OVERRIDES
        else {original.name: rendering.model_dump(mode="json", exclude={"metadata"})}
    )
    when = capture_time or CaptureTime(None, None)
    return {
        "sidecar_version": SIDECAR_VERSION,
        "picturesq_version": version,
        "original": {"name": original.name, "sha256": original_sha256},
        "output": {
            "name": output,
            **config.export.outputs[output].model_dump(mode="json"),
        },
        "look": None
        if look is None
        else {
            "name": look.key,
            "intensity": look.intensity,
            "parameters": dict(look.parameters),
            "sha256": look.sha256,
        },
        "metadata": metadata_document(when),
        "config": {"version": config.version, **rendered, "photos": photos},
    }


def metadata_document(when: CaptureTime) -> dict[str, Any]:
    """The sidecar's ``metadata`` section for a capture time."""
    return {
        "camera_time": None if when.camera is None else when.camera.isoformat(),
        "capture_time": None if when.corrected is None else when.corrected.isoformat(),
        "time_zone": when.time_zone,
    }


def sidecar_path(export_path: Path) -> Path:
    """``exports/web/IMG_1.jpg`` → ``exports/web/IMG_1.picturesq.json``."""
    return export_path.with_name(export_path.stem + SIDECAR_SUFFIX)


def write_sidecar(path: Path, document: dict[str, Any]) -> None:
    """Write ``document`` as indented JSON, atomically."""
    text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    atomic_write(path, text.encode("utf-8"))
