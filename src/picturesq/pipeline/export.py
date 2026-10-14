"""Render each original and write every enabled output (v0: decode -> display -> export)."""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from picturesq.colour.display import display_transform
from picturesq.colour.transfer import srgb_encode
from picturesq.config import DisplayTransformConfig, OutputConfig, ProjectConfig
from picturesq.decode import DecodeError, decode_original
from picturesq.export import resize_to_long_edge, to_8bit, write_jpeg
from picturesq.export.sharpen import sharpen
from picturesq.normalise import normalise

EXPORTS_DIRNAME = "exports"

# Scene-linear stages that run after decode, as (name, fn(image, config) -> image). Stages
# may modify the image in place. Grade's look operations (M3) are added here; render_scene
# and the stage sheet (scripts/stage_sheet.py) both iterate this, so a new stage gets a
# panel automatically.
SCENE_STAGES: tuple[
    tuple[str, Callable[[NDArray[np.float32], ProjectConfig], NDArray[np.float32]]], ...
] = (("normalise", normalise),)


def render_scene(image: NDArray[np.float32], config: ProjectConfig) -> NDArray[np.float32]:
    """Run the scene-linear stages after decode (normalise, grade), in place."""
    for _name, stage in SCENE_STAGES:
        image = stage(image, config)
    return image


def render_output(
    image: NDArray[np.float32], output: OutputConfig, display: DisplayTransformConfig
) -> NDArray[np.uint8]:
    """Resize, display transform, sRGB encode, sharpen and quantise ``image`` for one output.

    ``image`` is never modified.
    """
    sized = resize_to_long_edge(image, output.long_edge)
    # The same object back means `image` is still needed by the caller, so the transform
    # gets a new array. A resized array is ours to overwrite.
    result = display_transform(sized, display, out=None if sized is image else sized)
    srgb_encode(result, out=result)
    sharpen(result, output.sharpen)
    return to_8bit(result)


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
            image = render_scene(decode_original(original, config.decode), config)
            for name in names:
                spec = config.export.outputs[name]
                path = exports_dir / name / f"{original.stem}.jpg"
                write_jpeg(
                    render_output(image, spec, config.grade.display_transform),
                    path,
                    quality=spec.quality,
                )
                result.outputs[name] = path
            del image
        except (DecodeError, OSError) as error:
            result.error = str(error)
        result.seconds = time.perf_counter() - photo_started
        results.append(result)
        if on_photo is not None:
            on_photo(result)
    return ExportResult(photos=results, seconds=time.perf_counter() - started)
