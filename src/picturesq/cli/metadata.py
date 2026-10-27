"""`picturesq metadata`: correct the capture dates and times written into exports."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer

from picturesq.cli.config import EXIT_ERROR, EXIT_INVALID, fail, project_config
from picturesq.config import ProjectConfig, save_project_config
from picturesq.config.project import MetadataOverrides
from picturesq.config.time_shift import format_time_shift, parse_compact_shift
from picturesq.decode import find_originals, read_capture_exif
from picturesq.metadata import (
    CaptureTime,
    CaptureTimeError,
    camera_capture_time,
    parse_clock_time,
    photo_capture_time,
    shift_from_reference,
)
from picturesq.pipeline.export import EXPORTS_DIRNAME
from picturesq.pipeline.metadata import rewrite_exports

metadata_app = typer.Typer(
    name="metadata",
    help="Correct the capture dates and times written into exports (originals are never changed).",
    no_args_is_help=True,
)

ProjectArg = Annotated[str, typer.Argument(help="Project folder containing RAW originals.")]
JsonOption = Annotated[
    bool, typer.Option("--json", help="Print one JSON document on stdout instead of text.")
]
_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def _folder(project_arg: str) -> Path:
    project = Path(project_arg)
    if not project.is_dir():
        raise fail(f"{project} is not a folder", EXIT_INVALID)
    return project


def _clock_time(text: str) -> datetime:
    try:
        return parse_clock_time(text)
    except ValueError as error:
        raise fail(str(error), EXIT_INVALID) from None


def _show(value: datetime | None) -> str:
    return "-" if value is None else value.strftime(_TIME_FORMAT)


def _find_original(project: Path, name: str) -> Path:
    originals = find_originals(project)
    folded = name.casefold()
    for original in originals:
        if folded in (original.name.casefold(), original.stem.casefold()):
            return original
    raise fail(f"no original named {name!r} in {project}", EXIT_INVALID)


def _camera_time(original: Path) -> datetime | None:
    return camera_capture_time(read_capture_exif(original))


@dataclass(frozen=True)
class _Row:
    photo: str
    when: CaptureTime
    how: str


def _rows(project: Path, config: ProjectConfig) -> list[_Row]:
    rows = []
    for original in find_originals(project):
        camera = _camera_time(original)
        try:
            when = photo_capture_time(config, original.name, camera)
        except CaptureTimeError as error:
            raise fail(f"{original.name}: {error}", EXIT_ERROR) from None
        rows.append(_Row(original.name, when, when.how))
    return rows


@metadata_app.command()
def show(project: ProjectArg, as_json: JsonOption = False) -> None:
    """Each photo's camera time and the corrected time its exports carry.

    With --json, one document: {"time_shift": str, "time_zone": str | null, "photos":
    [{"photo": str, "camera_time": str | null, "capture_time": str | null, "how": str}]}
    with times as ISO 8601 text.
    """
    folder = _folder(str(project))
    config = project_config(folder, create=False)
    rows = _rows(folder, config)
    if as_json:
        document = {
            "time_shift": config.metadata.time_shift,
            "time_zone": config.metadata.time_zone,
            "photos": [
                {
                    "photo": row.photo,
                    "camera_time": None if row.when.camera is None else row.when.camera.isoformat(),
                    "capture_time": None
                    if row.when.corrected is None
                    else row.when.corrected.isoformat(),
                    "how": row.how,
                }
                for row in rows
            ],
        }
        typer.echo(json.dumps(document, indent=2))
        return
    zone = config.metadata.time_zone or "as the camera recorded"
    typer.echo(f"time shift {config.metadata.time_shift}, time zone {zone}")
    if not rows:
        typer.echo("no originals found")
        return
    width = max(len(row.photo) for row in rows)
    typer.echo(f"{'photo':<{width}}  {'camera time':<19}  {'corrected time':<19}  how")
    for row in rows:
        typer.echo(
            f"{row.photo:<{width}}  {_show(row.when.camera):<19}  "
            f"{_show(row.when.corrected):<19}  {row.how}"
        )


def _save(config: ProjectConfig, project: Path) -> None:
    save_project_config(config, project / "picturesq.yaml")


@metadata_app.command()
def shift(
    project: ProjectArg,
    photo: Annotated[
        str | None, typer.Option("--photo", help="A photo whose real time you know.")
    ] = None,
    actual: Annotated[
        str | None,
        typer.Option("--actual", help="That photo's real time, e.g. '2026-10-17 20:05'."),
    ] = None,
    by: Annotated[
        str | None,
        typer.Option("--by", help="Set the shift directly: '+1h', '-1d2h30m', '+9598d 10:05:00'."),
    ] = None,
    clear: Annotated[bool, typer.Option("--clear", help="Remove the shift.")] = False,
) -> None:
    """Set the project's time shift (`metadata.time_shift` in picturesq.yaml).

    Either from one photo whose real time you know (--photo with --actual: the shift is the
    difference from its camera time), directly (--by, which replaces any earlier shift), or
    removed (--clear).
    """
    folder = _folder(project)
    chosen = [photo is not None or actual is not None, by is not None, clear]
    if sum(chosen) != 1 or (photo is None) != (actual is None):
        raise fail("give --photo with --actual, or --by, or --clear (one of them)", EXIT_INVALID)
    if clear:
        value = timedelta(0)
    elif by is not None:
        try:
            value = parse_compact_shift(by)
        except ValueError as error:
            raise fail(str(error), EXIT_INVALID) from None
    else:
        assert photo is not None
        assert actual is not None
        original = _find_original(folder, photo)
        camera = _camera_time(original)
        if camera is None:
            raise fail(f"{original.name} records no capture time to compare with", EXIT_ERROR)
        real = _clock_time(actual)
        value = shift_from_reference(camera, real)
        typer.echo(f"{original.name}: camera says {_show(camera)}, actually {_show(real)}")
    config = project_config(folder, create=False)
    config.metadata.time_shift = format_time_shift(value)
    _save(config, folder)
    typer.echo(f"time shift set to {config.metadata.time_shift}")
    typer.echo(
        "exports pick it up on the next `picturesq export`, or now with `picturesq metadata apply`"
    )


@metadata_app.command(context_settings={"ignore_unknown_options": True})
def zone(
    project: ProjectArg,
    offset: Annotated[
        str | None, typer.Argument(help="Offset from UTC, e.g. +01:00 or -05:00.")
    ] = None,
    clear: Annotated[bool, typer.Option("--clear", help="Remove the time zone.")] = False,
) -> None:
    """Set the time zone of the corrected times (`metadata.time_zone`): the OffsetTime tags."""
    folder = _folder(project)
    if clear == (offset is not None):
        raise fail("give an offset like +01:00, or --clear", EXIT_INVALID)
    config = project_config(folder, create=False)
    try:
        config.metadata.time_zone = offset
    except ValueError:
        raise fail(
            f"{offset!r} is not a time zone; write it like +01:00 or -05:00", EXIT_INVALID
        ) from None
    _save(config, folder)
    typer.echo(f"time zone set to {offset}" if offset else "time zone cleared")


@metadata_app.command()
def time(
    project: ProjectArg,
    photo: Annotated[str, typer.Argument(help="The photo's file name.")],
    capture_time: Annotated[
        str | None, typer.Argument(help="The time it was taken, e.g. '2026-10-17 20:05'.")
    ] = None,
    clear: Annotated[
        bool, typer.Option("--clear", help="Remove this photo's capture time.")
    ] = False,
) -> None:
    """Set one photo capture time (`photos.<name>.metadata.capture_time`); wins over the shift."""
    folder = _folder(project)
    if clear == (capture_time is not None):
        raise fail("give the time, or --clear", EXIT_INVALID)
    original = _find_original(folder, photo)
    config = project_config(folder, create=False)
    value = None if capture_time is None else _clock_time(capture_time)
    current = config.photo(original.name)
    key = next(
        (k for k in config.photos if k.casefold() == original.name.casefold()), original.name
    )
    photos = dict(config.photos)
    photos[key] = current.model_copy(update={"metadata": MetadataOverrides(capture_time=value)})
    config.photos = photos
    _save(config, folder)
    typer.echo(
        f"{original.name}: capture time {_show(value)}" if value else f"{original.name}: cleared"
    )


@metadata_app.command()
def apply(
    project: ProjectArg,
    output: Annotated[
        list[str] | None, typer.Option("--output", help="Only this output (repeatable).")
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", help="The exports folder (default <project>/exports).")
    ] = None,
) -> None:
    """Rewrite the dates in exports already written, without re-rendering them.

    Only the JPEG's EXIF block changes; the image data stays byte for byte. Sidecars are
    updated to match. A time zone that was written earlier and then cleared is not removed
    (export again for that).
    """
    folder = _folder(project)
    config = project_config(folder, create=False)
    if output:
        unknown = [name for name in output if name not in config.export.outputs]
        if unknown:
            defined = ", ".join(sorted(config.export.outputs))
            raise fail(f"unknown output(s) {unknown}; defined: {defined}", EXIT_INVALID)
    names = output or list(config.export.enabled)
    exports_dir = out if out is not None else folder / EXPORTS_DIRNAME
    results = rewrite_exports(exports_dir, names, config, find_originals(folder))
    if not results:
        raise fail(f"no exported JPEGs in {exports_dir} for {', '.join(names)}", EXIT_ERROR)
    for result in results:
        if result.error is not None:
            typer.echo(f"{result.path.name}: FAILED ({result.error})")
        elif result.changed:
            when = result.capture_time
            typer.echo(f"{result.path.name}: {_show(when.corrected if when else None)}")
        else:
            typer.echo(f"{result.path.name}: already correct")
    failed = sum(result.error is not None for result in results)
    changed = sum(result.changed for result in results)
    typer.echo(f"{len(results)} export(s), {changed} rewritten, {failed} failed")
    if failed:
        raise typer.Exit(code=EXIT_ERROR)
