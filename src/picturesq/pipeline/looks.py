"""Resolving the looks a project's photos are graded with (reads the look library)."""

from picturesq.config import ProjectConfig, find_look
from picturesq.config.look import Look
from picturesq.photo import ResolvedLook


def resolve_look(
    config: ProjectConfig, name: str, library: dict[str, Look] | None = None
) -> ResolvedLook | None:
    """The look photo ``name`` is graded with, resolved; None for no look.

    Raises LookFileError for an unknown look, LookParameterError for bad parameter values.
    """
    choice = config.photo_look(name)
    if choice is None:
        return None
    look = find_look(choice.name, library)
    operations = tuple(look.file.resolve(choice.parameters))
    parameters = {
        key: choice.parameters.get(key, parameter.default)
        for key, parameter in look.file.parameters.items()
    }
    return ResolvedLook(
        key=look.key,
        sha256=look.sha256,
        intensity=choice.intensity,
        parameters=parameters,
        operations=operations,
    )


def check_looks(config: ProjectConfig, library: dict[str, Look] | None = None) -> None:
    """Resolve the project's look and every photo override's, so a bad name or value fails
    before any work starts. Raises like :func:`resolve_look`."""
    resolve_look(config, "", library)
    for name in config.photos:
        resolve_look(config, name, library)
