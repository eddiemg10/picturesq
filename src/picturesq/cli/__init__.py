"""Command-line interface. One module per verb as they are implemented."""

from typing import Annotated

import typer

from picturesq import __version__

app = typer.Typer(
    name="picturesq",
    help="Turn a folder of RAW photos into consistently edited exports.",
    no_args_is_help=True,
)

DirArg = Annotated[str, typer.Argument(help="Folder containing RAW files.")]


def _not_implemented(command: str, milestone: str) -> None:
    typer.echo(f"`picturesq {command}` is not implemented yet (planned for {milestone}).", err=True)
    raise typer.Exit(code=1)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version."),
    ] = False,
) -> None:
    """picturesq: develop, normalise, look, export."""


@app.command()
def run(directory: DirArg) -> None:
    """Run all stages: develop, normalise, look, export."""
    _not_implemented("run", "M1")


@app.command()
def develop(directory: DirArg) -> None:
    """Decode RAWs to scene-linear and build preview proxies."""
    _not_implemented("develop", "M1")


@app.command()
def normalise(directory: DirArg) -> None:
    """Compute per-image stats, normalise exposure and flag outliers."""
    _not_implemented("normalise", "M2")


@app.command()
def looks(directory: DirArg) -> None:
    """Render a photo x look contact sheet (terminal, PNG or web)."""
    _not_implemented("looks", "M3")


@app.command()
def ui(directory: DirArg) -> None:
    """Open the local web editor."""
    _not_implemented("ui", "M4")


@app.command()
def export(directory: DirArg) -> None:
    """Render full-resolution exports."""
    _not_implemented("export", "M1")


@app.command()
def schema() -> None:
    """Print the JSON schema for the config files."""
    _not_implemented("schema", "M1")


@app.command()
def doctor() -> None:
    """Check the environment (LibRaw, terminal graphics, memory)."""
    _not_implemented("doctor", "M1")
