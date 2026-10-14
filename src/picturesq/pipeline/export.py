"""Render each original and write every enabled output (v0: decode -> display -> export)."""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from picturesq.colour.display import display_transform
from picturesq.colour.transfer import srgb_encode
from picturesq.config import ProjectConfig
from picturesq.decode import DecodeError, decode_original
from picturesq.export import resize_to_long_edge, to_8bit, write_jpeg

EXPORTS_DIRNAME = "exports"


class StemCollisionError(Exception):
    """Two originals share a file name stem, so their exports would overwrite each other."""


@dataclass
class PhotoResult:
    """What happened to one photo."""

    name: str
    outputs: dict[str, Path] = field(default_factory=dict)
    error: str | None = None
    seconds: float = 0.0


@dataclass
class ExportResult:
    """Outcome of an export run, one entry per original, in order."""

    photos: list[PhotoResult]
    seconds: float

    @property
    def failed(self) -> int:
        return sum(1 for photo in self.photos if photo.error is not None)


def check_stems(originals: Sequence[Path]) -> None:
    """Raise StemCollisionError if two originals would write to the same export name.

    Names are compared case-insensitively: on Windows and macOS ``IMG.jpg`` and ``img.jpg``
    are one file, and the check must fail the same way on every OS.
    """
    seen: dict[str, Path] = {}
    for original in originals:
        other = seen.setdefault(original.stem.casefold(), original)
        if other is not original:
            raise StemCollisionError(
                f"{other.name} and {original.name} share the name {original.stem!r}; "
                "their exports would overwrite each other. Rename or move one."
            )


def export_originals(
    originals: Sequence[Path],
    config: ProjectConfig,
    exports_dir: Path,
    *,
    outputs: Sequence[str] | None = None,
    on_photo: Callable[[PhotoResult], None] | None = None,
) -> ExportResult:
    """Render ``originals`` and write ``<exports_dir>/<output>/<stem>.jpg`` per output.

    ``outputs`` restricts the run to the named outputs (default: the enabled ones, in
    config order). A photo that fails to decode is recorded and the run continues.
    Raises StemCollisionError before writing anything.
    """
    check_stems(originals)
    names = list(config.export.enabled if outputs is None else outputs)
    started = time.perf_counter()
    results: list[PhotoResult] = []
    for original in originals:
        photo_started = time.perf_counter()
        result = PhotoResult(name=original.name)
        try:
            image = decode_original(original, config.decode)
            # Normalise (M2) and grade (M3) slot in here, on `image`.
            for name in names:
                spec = config.export.outputs[name]
                sized = resize_to_long_edge(image, spec.long_edge)
                # The same object back means `image` is still needed by later outputs, so
                # the transform gets a new array. A resized array is ours to overwrite.
                display = display_transform(sized, out=None if sized is image else sized)
                srgb_encode(display, out=display)
                path = exports_dir / name / f"{original.stem}.jpg"
                write_jpeg(to_8bit(display), path, quality=spec.quality)
                result.outputs[name] = path
                del sized, display
            del image
        except (DecodeError, OSError) as error:
            result.error = str(error)
        result.seconds = time.perf_counter() - photo_started
        results.append(result)
        if on_photo is not None:
            on_photo(result)
    return ExportResult(photos=results, seconds=time.perf_counter() - started)
