"""`picturesq looks`: the look library, by category."""

import json
from typing import Any

import typer

from picturesq.cli.config import EXIT_ERROR, fail
from picturesq.config import LookFileError
from picturesq.config import look as look_files
from picturesq.config.look import Look


def look_document(look: Look) -> dict[str, Any]:
    """One look as ``picturesq looks --json`` prints it."""
    file = look.file
    return {
        "look": look.key,
        "category": file.category,
        "name": file.name,
        "description": file.description,
        "parameters": {
            name: parameter.model_dump(mode="json") for name, parameter in file.parameters.items()
        },
        "operations": [operation["op"] for operation in file.operations],
    }


def list_looks(category: str | None, *, as_json: bool) -> None:
    """Print the looks (of ``category``, if given), as text or JSON."""
    try:
        library = look_files.look_library()
    except LookFileError as error:
        raise fail(str(error), EXIT_ERROR) from None
    looks = [look for look in library.values() if category in (None, look.file.category)]
    if as_json:
        typer.echo(json.dumps({"looks": [look_document(look) for look in looks]}, indent=2))
        return
    if not looks:
        typer.echo("no looks" + (f" in {category}" if category else ""))
        return
    width = max(len(look.key) for look in looks)
    for look in looks:
        typer.echo(f"{look.key:<{width}}  {look.file.description}")
        for name, parameter in look.file.parameters.items():
            typer.echo(
                f"{'':<{width}}    {name}: {parameter.label}, {parameter.min} to "
                f"{parameter.max} (default {parameter.default})"
            )
