"""Command-line interface. One module per verb as they are implemented."""

import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from picturesq import __version__, parallel
from picturesq.cli.decode import decode_project
from picturesq.cli.export import MachineOptions, render_project
from picturesq.config import dump_schema, project_schema
from picturesq.pipeline.workers import parse_memory_budget

app = typer.Typer(
    name="picturesq",
    help="Turn a folder of RAW photos into consistently edited exports.",
    no_args_is_help=True,
)

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
def normalise(project: ProjectArg) -> None:
    """Compute per-photo stats, normalise exposure and flag outliers."""
    _not_implemented("normalise", "M2")


@app.command()
def preview(project: ProjectArg) -> None:
    """Render a contact sheet of photos x looks (terminal or PNG)."""
    _not_implemented("preview", "M3")


@app.command()
def looks() -> None:
    """List the look library, by category."""
    _not_implemented("looks", "M3")


@app.command()
def ui(project: ProjectArg) -> None:
    """Open the local web UI to choose looks and review photos."""
    _not_implemented("ui", "M4")


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


class SchemaKind(StrEnum):
    """Which file's schema `picturesq schema` prints (look files follow in M3)."""

    project = "project"


@app.command()
def schema(
    kind: Annotated[
        SchemaKind, typer.Argument(help="Which file: project (picturesq.yaml).")
    ] = SchemaKind.project,
) -> None:
    """Print the JSON Schema for picturesq.yaml."""
    sys.stdout.write(dump_schema(project_schema()))


@app.command()
def doctor() -> None:
    """Check the environment (LibRaw, terminal graphics, memory)."""
    _not_implemented("doctor", "M1")
