"""`picturesq export` and `picturesq run`: RAW folder in, JPEGs out."""

import json
import sys
from pathlib import Path

import typer

from picturesq.cli.config import EXIT_ERROR, EXIT_INVALID, fail, project_config
from picturesq.decode import find_originals
from picturesq.pipeline.export import (
    EXPORTS_DIRNAME,
    ExportResult,
    PhotoResult,
    StemCollisionError,
    export_originals,
)


def _photo_line(photo: PhotoResult) -> str:
    if photo.error is not None:
        return f"{photo.name}: FAILED ({photo.error})"
    outputs = ", ".join(photo.outputs)
    return f"{photo.name}: {outputs} ({photo.seconds:.1f}s)"


def _json_document(result: ExportResult) -> str:
    document = {
        "photos": [
            {
                "photo": photo.name,
                "outputs": {name: str(path) for name, path in photo.outputs.items()},
                "error": photo.error,
                "seconds": round(photo.seconds, 3),
            }
            for photo in result.photos
        ],
        "summary": {
            "photos": len(result.photos),
            "failed": result.failed,
            "seconds": round(result.seconds, 3),
        },
    }
    return json.dumps(document, indent=2)


def render_project(
    project_arg: str,
    *,
    create_config: bool,
    output_names: list[str] | None,
    out: Path | None,
    as_json: bool,
) -> None:
    """Shared body of `export` and `run`. Progress lines go to stdout; none in JSON mode."""
    project = Path(project_arg)
    if not project.is_dir():
        raise fail(f"{project} is not a folder", EXIT_INVALID)
    config = project_config(project, create=create_config)
    if output_names:
        unknown = [name for name in output_names if name not in config.export.outputs]
        if unknown:
            defined = ", ".join(sorted(config.export.outputs))
            raise fail(f"unknown output(s) {unknown}; defined: {defined}", EXIT_INVALID)
    originals = find_originals(project)
    if not originals:
        raise fail(f"no originals found in {project}", EXIT_ERROR)

    def report(photo: PhotoResult) -> None:
        if not as_json:
            typer.echo(_photo_line(photo))

    exports_dir = out if out is not None else project / EXPORTS_DIRNAME
    try:
        result = export_originals(
            originals, config, exports_dir, outputs=output_names or None, on_photo=report
        )
    except StemCollisionError as error:
        raise fail(str(error), EXIT_ERROR) from None

    if as_json:
        sys.stdout.write(_json_document(result) + "\n")
    else:
        typer.echo(f"{len(result.photos)} photo(s), {result.failed} failed, {result.seconds:.1f}s")
    if result.failed:
        raise typer.Exit(code=EXIT_ERROR)
