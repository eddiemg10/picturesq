"""`picturesq normalise`: how normalise sees the project, photo by photo, on proxies."""

import io
import json
import sys
import time
from pathlib import Path
from typing import Any

import typer

from picturesq import __version__
from picturesq.atomic import atomic_write
from picturesq.cli.config import EXIT_ERROR, EXIT_FLAGGED, EXIT_INVALID, fail, project_config
from picturesq.colour.transfer import FloatArray
from picturesq.decode import find_originals
from picturesq.pipeline.export import StemCollisionError, check_stems
from picturesq.pipeline.normalise import (
    NormaliseResult,
    normalise_originals,
    summarise,
    unmatched_overrides,
    write_stats,
)
from picturesq.pipeline.proxy import CACHE_DIRNAME
from picturesq.preview.normalise_sheet import (
    normalise_panel,
    normalise_sheet,
    render_panel_pixels,
)
from picturesq.preview.stage_sheet import Uint8Array


def photo_line(result: NormaliseResult, name_width: int = 0) -> str:
    """One line per photo: exposure (and scene contrast, if any), median after normalise,
    clipped, as-shot white, flags."""
    name = result.name.ljust(name_width)
    if result.error is not None:
        return f"{name}  FAILED ({result.error})"
    assert result.stats is not None
    if result.exposure is None:
        exposure = "normalise off"
    else:
        source = " (override)" if "exposure_ev" in result.overrides else ""
        exposure = f"exposure {result.exposure.ev:+.2f} EV{source}"
    contrast = result.scene_contrast
    if contrast is not None and contrast.contrast > 0.0:
        exposure += f"  scene contrast {contrast.contrast:.2f}"
    kelvin = None if result.info is None else result.info.as_shot_kelvin
    as_shot = "as-shot ?" if kelvin is None else f"as-shot {kelvin:.0f} K"
    flags = ", ".join(flag.name for flag in result.flags) or "ok"
    line = (
        f"{name}  {exposure}  median {result.stats.p50_ev:+.2f} EV  "
        f"clipped {result.stats.clipped:.2%}  {as_shot}  {flags}"
    )
    details = [f"    {flag.name}: {flag.message}" for flag in result.flags]
    return "\n".join([line, *details])


def summary_line(summary: dict[str, Any], seconds: float) -> str:
    median = summary["median_ev"]
    spread = (
        ""
        if median is None
        else f"; medians {median['median']:+.2f} EV (from {median['min']:+.2f} to "
        f"{median['max']:+.2f}, spread {median['spread']:.2f} EV)"
    )
    return (
        f"{summary['photos']} photo(s): {summary['flagged']} flagged, "
        f"{summary['failed']} failed{spread}, {seconds:.1f}s"
    )


def _write_sheet(
    path: Path, project: Path, results: list[NormaliseResult], pixels: dict[str, Uint8Array]
) -> None:
    summary = f"{len(results)} photo(s), {sum(1 for r in results if r.flags)} flagged"
    title = f"{project.resolve().name} · normalise · picturesq {__version__} · {summary}"
    panels = [normalise_panel(result, pixels.get(result.name)) for result in results]
    buffer = io.BytesIO()
    normalise_sheet(title, panels).save(buffer, format="PNG")
    atomic_write(path, buffer.getvalue())


def normalise_project(
    project_arg: str, *, as_json: bool, strict: bool, png: Path | None = None
) -> None:
    """Body of `picturesq normalise`. Photo lines go to stdout as they finish; none in JSON."""
    project = Path(project_arg)
    if not project.is_dir():
        raise fail(f"{project} is not a folder", EXIT_INVALID)
    config = project_config(project, create=False)
    originals = find_originals(project)
    if not originals:
        raise fail(f"no originals found in {project}", EXIT_ERROR)
    try:
        check_stems(originals)
    except StemCollisionError as error:
        raise fail(str(error), EXIT_ERROR) from None
    unmatched = unmatched_overrides(config, originals)
    for name in unmatched:
        typer.echo(f"warning: photos: {name} names no original in {project}", err=True)

    width = max(len(original.name) for original in originals)

    def report(result: NormaliseResult) -> None:
        if not as_json:
            typer.echo(photo_line(result, width))

    started = time.perf_counter()
    cache_dir = project / CACHE_DIRNAME
    pixels: dict[str, Uint8Array] = {}

    def render(result: NormaliseResult, image: FloatArray) -> None:
        pixels[result.name] = render_panel_pixels(image, config)

    results = normalise_originals(
        originals, config, cache_dir, on_photo=report, on_image=render if png else None
    )
    summary = summarise(results, unmatched)
    write_stats(results, summary, cache_dir)
    if png is not None:
        try:
            _write_sheet(png, project, results, pixels)
        except OSError as error:
            raise fail(f"cannot write {png}: {error}", EXIT_ERROR) from None
        if not as_json:
            typer.echo(f"wrote {png}")
    seconds = time.perf_counter() - started
    if as_json:
        document = {
            "version": __version__,
            "photos": [result.to_dict() for result in results],
            "summary": {**summary, "seconds": round(seconds, 3)},
        }
        sys.stdout.write(json.dumps(document, indent=2) + "\n")
    else:
        typer.echo(summary_line(summary, seconds))
    if summary["failed"]:
        raise typer.Exit(code=EXIT_ERROR)
    if strict and summary["flagged"]:
        raise typer.Exit(code=EXIT_FLAGGED)
