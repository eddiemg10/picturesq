"""Loading the project config from a command, with the CLI's error contract."""

from pathlib import Path

import typer

from picturesq.config import (
    CONFIG_FILENAME,
    ConfigError,
    ProjectConfig,
    load_project_config,
    save_project_config,
)

EXIT_ERROR = 1
EXIT_INVALID = 2
"""Exit code for invalid config or usage (project plan section 7)."""
EXIT_FLAGGED = 3
"""Exit code when the command completed but a photo has a flag (only with ``--strict``)."""


def fail(message: str, code: int) -> typer.Exit:
    """Print ``error: message`` on stderr; raise the result to exit with ``code``."""
    typer.echo(f"error: {message}", err=True)
    return typer.Exit(code=code)


def load_config_or_exit(project: Path) -> ProjectConfig:
    """Load ``<project>/picturesq.yaml``; on any config problem print it and exit 2."""
    try:
        return load_project_config(project / CONFIG_FILENAME)
    except ConfigError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(code=EXIT_INVALID) from None


def project_config(project: Path, *, create: bool) -> ProjectConfig:
    """Load the project config; if missing use defaults, writing them only when ``create``."""
    path = project / CONFIG_FILENAME
    if path.exists():
        return load_config_or_exit(project)
    config = ProjectConfig()
    if create:
        save_project_config(config, path)
        typer.echo(f"created {CONFIG_FILENAME} with defaults", err=True)
    return config
