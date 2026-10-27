"""`picturesq preview`: a contact sheet of the project's photos through looks."""

import io
import time
from pathlib import Path

import typer

from picturesq import __version__
from picturesq.atomic import atomic_write
from picturesq.cli.config import EXIT_ERROR, EXIT_INVALID, fail, project_config
from picturesq.colour.transfer import FloatArray
from picturesq.config import LookFileError, LookParameterError, find_look
from picturesq.config import look as look_files
from picturesq.config.look import Look
from picturesq.decode import find_originals
from picturesq.pipeline.export import StemCollisionError, check_stems
from picturesq.pipeline.normalise import NormaliseResult, normalise_originals
from picturesq.pipeline.proxy import CACHE_DIRNAME
from picturesq.preview.look_sheet import (
    failed_panel,
    look_sheet,
    render_variant,
    variant_panel,
    variants,
)
from picturesq.preview.stage_sheet import Panel

PREVIEWS_DIRNAME = "previews"
DEFAULT_SHEET = "sheet.png"


def _chosen_looks(
    library: dict[str, Look], category: str | None, names: list[str] | None
) -> list[Look]:
    if names:
        try:
            return [find_look(name, library) for name in names]
        except LookFileError as error:
            raise fail(str(error), EXIT_INVALID) from None
    return [look for look in library.values() if category in (None, look.file.category)]


def preview_project(
    project_arg: str,
    *,
    category: str | None,
    look_names: list[str] | None,
    png: Path | None,
) -> None:
    """Body of `picturesq preview`: render every photo's row, write the sheet, print its path."""
    project = Path(project_arg)
    if not project.is_dir():
        raise fail(f"{project} is not a folder", EXIT_INVALID)
    config = project_config(project, create=False)
    originals = find_originals(project)
    if not originals:
        raise fail(f"no originals found in {project}", EXIT_ERROR)
    try:
        check_stems(originals)
        library = look_files.look_library()
    except (StemCollisionError, LookFileError) as error:
        raise fail(str(error), EXIT_ERROR) from None
    looks = _chosen_looks(library, category, look_names)
    started = time.perf_counter()
    cache_dir = project / CACHE_DIRNAME
    rows: dict[str, list[Panel]] = {}

    def render(result: NormaliseResult, image: FloatArray) -> None:
        try:
            row = variants(config, result.name, looks, library)
        except (LookFileError, LookParameterError) as error:
            rows[result.name] = [failed_panel(result.name, str(error))]
            return
        rows[result.name] = [
            variant_panel(
                result.name,
                variant,
                render_variant(image, config, result.name, result.info, variant),
            )
            for variant in row
        ]

    results = normalise_originals(originals, config, cache_dir, on_image=render)
    sheet_rows = [
        rows.get(result.name) or [failed_panel(result.name, result.error or "not rendered")]
        for result in results
    ]
    seconds = time.perf_counter() - started
    chosen = category or (", ".join(look.key for look in looks) if look_names else "all looks")
    title = (
        f"{project.resolve().name} · preview · {chosen} · picturesq {__version__} · "
        f"{len(results)} photo(s) x {len(looks)} look(s)"
    )
    path = png if png is not None else cache_dir / PREVIEWS_DIRNAME / DEFAULT_SHEET
    buffer = io.BytesIO()
    look_sheet(title, sheet_rows).save(buffer, format="PNG")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, buffer.getvalue())
    except OSError as error:
        raise fail(f"cannot write {path}: {error}", EXIT_ERROR) from None
    failed = sum(1 for result in results if result.error is not None)
    typer.echo(f"wrote {path} ({len(results)} photo(s), {len(looks)} look(s), {seconds:.1f} s)")
    if failed:
        raise fail(f"{failed} photo(s) failed", EXIT_ERROR)
