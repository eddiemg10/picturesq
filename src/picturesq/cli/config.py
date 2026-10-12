"""Loading the project config from a command, with the CLI's error contract."""

from pathlib import Path

import typer

from picturesq.config import CONFIG_FILENAME, ConfigError, ProjectConfig, load_project_config

EXIT_INVALID = 2
"""Exit code for invalid config or usage (project plan section 7)."""


def load_config_or_exit(project: Path) -> ProjectConfig:
    """Load ``<project>/picturesq.yaml``; on any config problem print it and exit 2."""
    try:
        return load_project_config(project / CONFIG_FILENAME)
    except ConfigError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(code=EXIT_INVALID) from None
