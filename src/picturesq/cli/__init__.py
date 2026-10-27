"""Command-line interface. One module per verb as they are implemented."""

import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from picturesq import __version__, parallel
from picturesq.cli.decode import decode_project
from picturesq.cli.doctor import run_doctor
from picturesq.cli.export import MachineOptions, render_project
from picturesq.cli.looks import list_looks
from picturesq.cli.metadata import metadata_app
from picturesq.cli.normalise import normalise_project
from picturesq.cli.preview import preview_project
from picturesq.cli.ui import serve_project
from picturesq.config import dump_schema, look_schema, project_schema
from picturesq.pipeline.workers import parse_memory_budget

app = typer.Typer(
    name="picturesq",
    help="Turn a folder of RAW photos into consistently edited exports.",
    no_args_is_help=True,
)
app.add_typer(metadata_app, name="metadata")

ProjectArg = Annotated[str, typer.Argument(help="Project folder containing RAW originals.")]
OutOption = Annotated[
    Path | None,
    typer.Option("--out", help="Write exports here instead of <project>/exports."),
]
JsonOption = Annotated[
    bool, typer.Option("--json", help="Print one JSON document on stdout instead of text.")
]


def _not_implemented(command: str, milestone: str) -> None:
    typer.echo(f"`picturesq {command}` is not implemented yet (planned for {milestone}).", err=True)
    raise typer.Exit(code=1)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


def _memory_budget(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return parse_memory_budget(value)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from None


@app.callback()
def main(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version."),
    ] = False,
    threads: Annotated[
        int | None,
        typer.Option(
            "--threads",
            min=1,
            envvar="PICTURESQ_THREADS",
            help="Threads per photo (default: one per physical core).",
        ),
    ] = None,
    block_pixels: Annotated[
        int | None,
        typer.Option(
            "--block-pixels",
            min=1024,
            envvar="PICTURESQ_BLOCK_PIXELS",
            help="Pixels per block of work (default: from the CPU cache size).",
        ),
    ] = None,
    workers: Annotated[
        int | None,
        typer.Option(
            "--workers",
            min=1,
            envvar="PICTURESQ_WORKERS",
            help="Photos exported at once, each in its own process "
            "(default: as many as the memory budget and the cores allow).",
        ),
    ] = None,
    memory_budget: Annotated[
        str | None,
        typer.Option(
            "--memory-budget",
            envvar="PICTURESQ_MEMORY_BUDGET",
            help="Memory all workers together may use, e.g. 3GB or 2.5GiB "
            "(default: 60% of the memory available at the start).",
        ),
    ] = None,
) -> None:
    """picturesq: decode, normalise, grade, export."""
    # Machine settings, not project config: they never change the output (bit-identical).
    parallel.use(parallel.auto(threads=threads, block_pixels=block_pixels))
    ctx.obj = MachineOptions(
        threads=threads, workers=workers, memory_budget=_memory_budget(memory_budget)
    )


@app.command()
def run(
    ctx: typer.Context, project: ProjectArg, out: OutOption = None, as_json: JsonOption = False
) -> None:
    """Run the whole pipeline: decode, normalise, grade, export.

    Creates picturesq.yaml with defaults if missing. For now this is decode + export.
    """
    render_project(
        project, create_config=True, output_names=None, out=out, as_json=as_json, machine=ctx.obj
    )


@app.command()
def decode(project: ProjectArg, as_json: JsonOption = False) -> None:
    """Build the proxy cache: a small scene-linear copy of each photo for previews and the UI.

    Proxies already current are reused. Doesn't create picturesq.yaml.
    """
    decode_project(project, as_json=as_json)


@app.command()
def normalise(
    project: ProjectArg,
    as_json: JsonOption = False,
    strict: Annotated[
        bool, typer.Option("--strict", help="Exit 3 if any photo has a flag (after printing).")
    ] = False,
    png: Annotated[
        Path | None,
        typer.Option(
            "--png",
            help="Also write a contact sheet of the normalised photos (neutral render) here.",
        ),
    ] = None,
) -> None:
    """Show how normalise sees each photo: exposure, stats, white balance check and flags.

    Works on proxies (built if missing), so it takes seconds; changes no photo. Writes
    .picturesq/stats/<stem>.json per photo and .picturesq/stats/summary.json. Doesn't create
    picturesq.yaml. Warns about photos: overrides naming no original. Exits 1 if a photo
    failed, else 3 with --strict if any photo has a flag. With --png, also writes a contact
    sheet: one panel per photo, captioned with its exposure and flags, flagged photos in amber.

    With --json, one document: {"version": str, "photos": [{"photo": name, "proxy_key": str,
    "normalised": bool, "exposure_ev": EV|null, "correction_ev": EV|null, "overrides":
    {key: value}, "info": {"as_shot_xy", "as_shot_kelvin", "as_shot_tint",
    "baseline_exposure_ev", "clip_level"}, "stats": {"p1_ev", "p5_ev", "p50_ev", "p95_ev",
    "p99_ev", "dynamic_range_ev", "clipped", "mean_chroma"}, "white_balance":
    {"as_shot_kelvin", "as_shot_tint", "brightest", "grey", "disagrees", "reason"}, "flags":
    [{"flag": name, "message": str, "details": {...}}], "error": str|null}], "summary":
    {"photos": n, "failed": n, "flagged": n, "flags": {name: n}, "flagged_photos": [name],
    "failed_photos": [name], "median_ev": {"median", "min", "max", "spread"}|null,
    "unmatched_overrides": [name], "seconds": s}}. A failed photo has null info, stats and
    white_balance. The stats files hold the same objects (each with "version"; the summary
    without "seconds").
    """
    normalise_project(project, as_json=as_json, strict=strict, png=png)


class CategoryName(StrEnum):
    """A look category, for `picturesq looks --category`."""

    bw = "bw"
    cold = "cold"
    warm = "warm"
    cinematic = "cinematic"


@app.command()
def looks(
    category: Annotated[
        CategoryName | None, typer.Option("--category", help="Only this category.")
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """List the look library, by category, with each look's parameters.

    With --json, one document: {"looks": [{"look": "category/name", "category": str,
    "name": str, "description": str, "parameters": {name: {"default", "min", "max",
    "label"}}, "operations": [op]}]}, in category then name order.
    """
    list_looks(None if category is None else category.value, as_json=as_json)


@app.command()
def ui(
    project: ProjectArg,
    port: Annotated[int, typer.Option("--port", min=1, max=65535, help="Port to serve on.")] = 8765,
    open_browser: Annotated[
        bool, typer.Option("--open/--no-open", help="Open the UI in the default browser.")
    ] = True,
) -> None:
    """Open the local web UI to choose looks and review photos.

    Serves on localhost only. Every change is saved to picturesq.yaml as you make it; edits
    to that file from elsewhere (an agent) show up in the browser within a second.
    Proxies are built on first view if missing (`picturesq decode` builds them up front).
    """
    serve_project(project, host="127.0.0.1", port=port, open_browser=open_browser)


@app.command()
def export(
    ctx: typer.Context,
    project: ProjectArg,
    output: Annotated[
        list[str] | None,
        typer.Option("--output", help="Write only this output (repeatable)."),
    ] = None,
    out: OutOption = None,
    as_json: JsonOption = False,
) -> None:
    """Render originals and write every enabled output.

    Uses default settings if picturesq.yaml is missing, without creating it.
    """
    render_project(
        project,
        create_config=False,
        output_names=output,
        out=out,
        as_json=as_json,
        machine=ctx.obj,
    )


@app.command()
def preview(
    project: ProjectArg,
    category: Annotated[
        CategoryName | None, typer.Option("--category", help="Only this category's looks.")
    ] = None,
    look: Annotated[
        list[str] | None,
        typer.Option("--look", help="Only this look, as category/name (repeatable)."),
    ] = None,
    png: Annotated[
        Path | None,
        typer.Option("--png", help="Write the sheet here (default .picturesq/previews/sheet.png)."),
    ] = None,
) -> None:
    """Render a contact sheet of the photos through looks, from proxies, in seconds.

    One row per photo: the neutral render, the photo's current grade (look and adjustments
    from picturesq.yaml) when it has one, then each look (all, a --category, or the --look
    ones). A look is shown at the photo's own intensity and parameters if it's the photo's
    look, else at 100 % with its defaults; the photo's adjustments apply to every look.
    Builds missing proxies; doesn't create picturesq.yaml. Prints the sheet's path.
    """
    preview_project(
        project,
        category=None if category is None else category.value,
        look_names=look,
        png=png,
    )


class SchemaKind(StrEnum):
    """Which file's schema `picturesq schema` prints."""

    project = "project"
    look = "look"


@app.command()
def schema(
    kind: Annotated[
        SchemaKind,
        typer.Argument(help="Which file: project (picturesq.yaml) or look (a look file)."),
    ] = SchemaKind.project,
) -> None:
    """Print the JSON Schema for picturesq.yaml or for a look file."""
    sys.stdout.write(dump_schema(look_schema() if kind is SchemaKind.look else project_schema()))


@app.command()
def doctor(ctx: typer.Context, as_json: JsonOption = False) -> None:
    """Check the environment: libraries, CPU, parallelism and terminal graphics.

    Each check is ok, warning or error; exits 1 if any is an error. Terminal graphics is a
    guess from environment variables. With --json, one document:
    {"checks": [{"check": id, "status": "ok"|"warning"|"error", "value": str,
    "message": str, "data": {...}}], "summary": {"ok": n, "warning": n, "error": n}}.
    Check ids: picturesq, python, platform, libraw, libraw_features, rawpy, numpy, pillow,
    tifffile, pydantic, pillow_features, cpus, cache, threads, block_size, terminal_graphics.
    """
    run_doctor(ctx, as_json=as_json)
