"""YAML load/save for config models. Writes are atomic (ADR-0004)."""

from pathlib import Path

import yaml
from pydantic import ValidationError

from picturesq.atomic import atomic_write
from picturesq.config.project import ProjectConfig


class ConfigError(Exception):
    """A config file is missing, unreadable or invalid. The message is user-facing."""


def _format_validation_error(path: Path, error: ValidationError) -> str:
    lines = [f"{path.name} is invalid ({error.error_count()} problem(s)):"]
    for item in error.errors():
        location = ".".join(str(part) for part in item["loc"]) or "(top level)"
        lines.append(f"  {location}: {item['msg']} (got {item.get('input')!r})")
    return "\n".join(lines)


def load_project_config(path: Path) -> ProjectConfig:
    """Read and validate a ``picturesq.yaml``. An empty file gives the defaults."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(f"{path} does not exist") from None
    except OSError as error:
        raise ConfigError(f"cannot read {path}: {error}") from None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ConfigError(f"{path.name} is not valid YAML: {error}") from None
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} must be a mapping, got {type(data).__name__}")
    try:
        return ProjectConfig.model_validate(data)
    except ValidationError as error:
        raise ConfigError(_format_validation_error(path, error)) from None


def dump_project_config(config: ProjectConfig) -> str:
    """Serialise to YAML, keys in model order."""
    return yaml.safe_dump(
        config.model_dump(mode="json"), sort_keys=False, allow_unicode=True, width=100
    )


def save_project_config(config: ProjectConfig, path: Path) -> None:
    """Write atomically: a temp file in the same folder, then rename over ``path``.

    A crash mid-write leaves the old file intact, and a watcher (the UI) never reads a
    half-written file.
    """
    atomic_write(path, dump_project_config(config).encode("utf-8"))
