"""Command-line interface. One module per verb as they are implemented."""

from typing import Annotated

import typer

from picturesq import __version__

app = typer.Typer(
    name="picturesq",
    help="Turn a folder of RAW photos into consistently edited exports.",
    no_args_is_help=True,
)

ProjectArg = Annotated[str, typer.Argument(help="Project folder containing RAW originals.")]


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
    """picturesq: decode, normalise, grade, export."""


@app.command()
def run(project: ProjectArg) -> None:
    """Run the whole pipeline: decode, normalise, grade, export."""
    _not_implemented("run", "M1")


@app.command()
def decode(project: ProjectArg) -> None:
    """Decode originals to scene-linear and build proxies."""
    _not_implemented("decode", "M1")


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
def export(project: ProjectArg) -> None:
    """Render originals at full resolution and write every enabled output."""
    _not_implemented("export", "M1")


@app.command()
def schema() -> None:
    """Print the JSON schema for picturesq.yaml and look files."""
    _not_implemented("schema", "M1")


@app.command()
def doctor() -> None:
    """Check the environment (LibRaw, terminal graphics, memory)."""
    _not_implemented("doctor", "M1")
