"""Render each original and write every enabled output, each with EXIF and a sidecar."""

import multiprocessing
import time
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
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
from picturesq.photo import UNNAMED, PhotoContext
from picturesq.pipeline.workers import WorkerPlan, photos_to_start

EXPORTS_DIRNAME = "exports"
SOFTWARE = f"picturesq {__version__}"
SHARPEN_BAND_RADII = 8
"""Sharpening bands are at least this many blur radii tall (measured in #68: 8-row bands
on a 7680 px wide image were 2.5x slower than 32-row ones)."""

# Scene-linear stages that run after decode, as (name, fn(image, config, photo) -> image).
# Stages may modify the image in place. Grade's look operations (M3) are added here; render_scene
# and the stage sheet (scripts/stage_sheet.py) both iterate this, so a new stage gets a
# panel automatically.
SceneStage = Callable[[NDArray[np.float32], ProjectConfig, PhotoContext], NDArray[np.float32]]
SCENE_STAGES: tuple[tuple[str, SceneStage], ...] = (("normalise", normalise), ("grade", grade))


def render_scene(
    image: NDArray[np.float32], config: ProjectConfig, photo: PhotoContext = UNNAMED
) -> NDArray[np.float32]:
    """Run the scene-linear stages after decode (normalise, grade) for ``photo``, in place."""
    for _name, stage in SCENE_STAGES:
        image = stage(image, config, photo)
    return image


def render_output(
    image: NDArray[np.float32],
    output: OutputConfig,
    display: DisplayTransformConfig,
    *,
    consume: bool = False,
) -> NDArray[np.uint8]:
    """Resize, display transform, sRGB encode, sharpen and quantise ``image`` for one output.

    Works in blocks on several cores (``picturesq.parallel``): the display transform and
    sRGB encoding a block of pixels at a time, then sharpening and quantising a block of
    rows at a time, straight into the 8-bit result.

    ``image`` is left unchanged unless ``consume`` is set: then the caller is done with it,
    and an output that isn't resized transforms it in place instead of into a new array,
    saving one full-resolution float copy (12 bytes per pixel). The pixels are the same
    either way. A resized output always works on its own (smaller) array.
    """
    sized = resize_to_long_edge(image, output.long_edge)
    # The same object back means no resize happened: transform into a new array unless the
    # caller has given `image` up. A resized array is ours to overwrite.
    encoded = sized if sized is not image or consume else np.empty_like(sized)
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
    plan: WorkerPlan | None = None,
) -> ExportResult:
    """Render ``originals`` and write ``<exports_dir>/<output>/<stem>.jpg`` per output, each
    with the original's capture EXIF and a ``<stem>.picturesq.json`` sidecar.

    ``outputs`` restricts the run to the named outputs (default: the enabled ones, in
    config order). A photo that fails to decode is recorded and the run continues.
    Raises StemCollisionError before writing anything.

    Without a ``plan`` (``picturesq.pipeline.workers``), photos export one at a time in
    this process with ``parallel.current()`` threads. A plan with several workers exports
    photos at once in worker processes, largest first, as the memory budget allows. Either
    way the results are in ``originals`` order and the files are identical; ``on_photo``
    is called here as each photo finishes (with workers, in finishing order).
    """
    check_stems(originals)
    names = list(config.export.enabled if outputs is None else outputs)
    started = time.perf_counter()
    if plan is not None and plan.workers > 1 and len(originals) > 1:
        results = _export_in_workers(originals, config, exports_dir, names, on_photo, plan)
    else:
        settings = parallel.current()
        if plan is not None:
            settings = parallel.Parallelism(plan.threads or plan.cores, settings.block_pixels)
        results = []
        with parallel.using(settings):
            for original in originals:
                results.append(export_photo(original, config, exports_dir, names))
                if on_photo is not None:
                    on_photo(results[-1])
    return ExportResult(photos=results, seconds=time.perf_counter() - started)


def export_photo(
    original: Path, config: ProjectConfig, exports_dir: Path, names: Sequence[str]
) -> PhotoResult:
    """Export one original to the outputs ``names``; a decode or file error is recorded."""
    photo_started = time.perf_counter()
    result = PhotoResult(name=original.name)
    try:
        capture = read_capture_exif(original)
        original_sha256 = sha256_file(original)
        photo = PhotoContext(name=original.name)
        image = render_scene(decode_original(original, config.decode), config, photo)
        for index, name in enumerate(names):
            spec = config.export.outputs[name]
            path = exports_dir / name / f"{original.stem}.jpg"
            # The last output may use up the scene image: nothing reads it afterwards.
            last = index == len(names) - 1
            pixels = render_output(image, spec, config.grade.display_transform, consume=last)
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
    return result


ExportPhoto = Callable[[Path, ProjectConfig, Path, Sequence[str]], PhotoResult]

_WORKER_STOPPED = (
    "its worker stopped unexpectedly (out of memory?); try a smaller --memory-budget or --workers 1"
)


def _in_worker(
    export: ExportPhoto,
    settings: parallel.Parallelism,
    original: Path,
    config: ProjectConfig,
    exports_dir: Path,
    names: Sequence[str],
) -> PhotoResult:
    """Runs in a worker: this photo's threads, then the export."""
    parallel.use(settings)
    return export(original, config, exports_dir, names)


def _export_in_workers(
    originals: Sequence[Path],
    config: ProjectConfig,
    exports_dir: Path,
    names: Sequence[str],
    on_photo: Callable[[PhotoResult], None] | None,
    plan: WorkerPlan,
    export: ExportPhoto = export_photo,
) -> list[PhotoResult]:
    """``export`` each original in ``plan.workers`` worker processes, as the plan allows.

    The processes are started fresh (``spawn``), never forked: a fork copies this process's
    thread pools without their threads, and a forked numpy can deadlock on a lock one of
    those threads held. A fresh process costs ~1 s of imports, once per worker. ``export``
    must be importable by name (a module-level function), as the worker imports it afresh.
    """
    block_pixels = parallel.current().block_pixels
    results: list[PhotoResult | None] = [None] * len(originals)
    pending = plan.order()
    running: dict[Future[PhotoResult], int] = {}

    def finish(index: int, result: PhotoResult) -> None:
        results[index] = result
        if on_photo is not None:
            on_photo(result)

    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(plan.workers, mp_context=context) as pool:
        try:
            while pending or running:
                for start in photos_to_start(plan, pending, list(running.values())):
                    pending.remove(start.index)
                    settings = parallel.Parallelism(start.threads, block_pixels)
                    future = pool.submit(
                        _in_worker,
                        export,
                        settings,
                        originals[start.index],
                        config,
                        exports_dir,
                        names,
                    )
                    running[future] = start.index
                done, _ = wait(running, return_when=FIRST_COMPLETED)
                for future in done:
                    index = running.pop(future)
                    try:
                        finish(index, future.result())
                    except BrokenProcessPool:
                        # The operating system stopped a worker, most likely for lack of
                        # memory. The pool is unusable: every photo not yet done fails.
                        for failed in [index, *pending]:
                            name = originals[failed].name
                            finish(failed, PhotoResult(name, error=_WORKER_STOPPED))
                        pending = []
        except BaseException:
            pool.shutdown(wait=True, cancel_futures=True)
            raise
    return [result for result in results if result is not None]
