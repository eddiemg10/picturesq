"""Render each original and write every enabled output, each with EXIF and a sidecar."""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from picturesq import __version__, parallel
from picturesq.colour.agx import AgxCurve, agx
from picturesq.colour.filters import gaussian_radius
from picturesq.colour.transfer import srgb_encode
from picturesq.config import DisplayTransformConfig, OutputConfig, ProjectConfig
from picturesq.decode import DecodeError, decode_original, read_capture_exif
from picturesq.export import (
    export_exif,
    resize_to_long_edge,
    sha256_file,
    sidecar_document,
    sidecar_path,
    to_8bit,
    write_jpeg,
    write_sidecar,
)
from picturesq.export.sharpen import sharpened_rows
from picturesq.grade import grade
from picturesq.normalise import normalise

EXPORTS_DIRNAME = "exports"
SOFTWARE = f"picturesq {__version__}"
SHARPEN_BAND_RADII = 8
"""Sharpening bands are at least this many blur radii tall (measured in #68: 8-row bands
on a 7680 px wide image were 2.5x slower than 32-row ones)."""

# Scene-linear stages that run after decode, as (name, fn(image, config) -> image). Stages
# may modify the image in place. Grade's look operations (M3) are added here; render_scene
# and the stage sheet (scripts/stage_sheet.py) both iterate this, so a new stage gets a
# panel automatically.
SCENE_STAGES: tuple[
    tuple[str, Callable[[NDArray[np.float32], ProjectConfig], NDArray[np.float32]]], ...
] = (("normalise", normalise), ("grade", grade))


def render_scene(image: NDArray[np.float32], config: ProjectConfig) -> NDArray[np.float32]:
    """Run the scene-linear stages after decode (normalise, grade), in place."""
    for _name, stage in SCENE_STAGES:
        image = stage(image, config)
    return image


def render_output(
    image: NDArray[np.float32], output: OutputConfig, display: DisplayTransformConfig
) -> NDArray[np.uint8]:
    """Resize, display transform, sRGB encode, sharpen and quantise ``image`` for one output.

    ``image`` is never modified. Works in blocks on several cores (``picturesq.parallel``):
    the display transform and sRGB encoding a block of pixels at a time, then sharpening
    and quantising a block of rows at a time, straight into the 8-bit result. Only one
    full-size float copy exists besides ``image``.
    """
    sized = resize_to_long_edge(image, output.long_edge)
    # The same object back means `image` is still needed by the caller, so the transform
    # gets a new array. A resized array is ours to overwrite.
    encoded = sized if sized is not image else np.empty_like(sized)
    curve = AgxCurve.from_config(display)
    source, target = sized.reshape(-1, 3), encoded.reshape(-1, 3)

    def encode(block: slice) -> None:
        agx(source[block], curve, out=target[block])
        srgb_encode(target[block], out=target[block])

    parallel.run(partial(encode, block) for block in parallel.pixel_blocks(len(source)))
    height, width = encoded.shape[:2]
    pixels = np.empty(encoded.shape, dtype=np.uint8)

    def finish(top: int, bottom: int) -> None:
        pixels[top:bottom] = to_8bit(sharpened_rows(encoded, output.sharpen, top, bottom))

    # Each band also blurs its sharpening radius above and below; tall bands keep that small.
    min_rows = SHARPEN_BAND_RADII * gaussian_radius(output.sharpen.radius)
    bands = parallel.row_blocks(height, width, min_rows=min_rows)
    parallel.run(partial(finish, *rows) for rows in bands)
    return pixels


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
    """Render ``originals`` and write ``<exports_dir>/<output>/<stem>.jpg`` per output, each
    with the original's capture EXIF and a ``<stem>.picturesq.json`` sidecar.

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
            capture = read_capture_exif(original)
            original_sha256 = sha256_file(original)
            image = render_scene(decode_original(original, config.decode), config)
            for name in names:
                spec = config.export.outputs[name]
                path = exports_dir / name / f"{original.stem}.jpg"
                pixels = render_output(image, spec, config.grade.display_transform)
                height, width = pixels.shape[:2]
                exif = export_exif(capture, width=width, height=height, software=SOFTWARE)
                write_jpeg(pixels, path, quality=spec.quality, exif=exif)
                del pixels
                # After the JPEG: a sidecar on disk means its export is complete.
                document = sidecar_document(
                    version=__version__,
                    original=original,
                    original_sha256=original_sha256,
                    output=name,
                    config=config,
                )
                write_sidecar(sidecar_path(path), document)
                result.outputs[name] = path
            del image
        except (DecodeError, OSError) as error:
            result.error = str(error)
        result.seconds = time.perf_counter() - photo_started
        results.append(result)
        if on_photo is not None:
            on_photo(result)
    return ExportResult(photos=results, seconds=time.perf_counter() - started)
