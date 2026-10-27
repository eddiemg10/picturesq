"""Look files: a look's metadata, parameters and operations (plan §6.2, ADR-0019).

An operation's numeric value can be a parameter reference, ``$name``: the value comes from
the parameter, which the UI shows as a slider between its ``min`` and ``max``. A look file
is valid only if every reference names a parameter, every parameter is used, and each
operation is valid with its parameters at their default, minimum and maximum (and
:meth:`LookFile.resolve` validates the values it is given).

Built-in look files are package data in ``picturesq/grade/looks/<category>/<name>.yaml``;
:func:`look_library` loads them.
"""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from picturesq.config.operations import AnyOperation, Operation

Category = Literal["bw", "cold", "warm", "cinematic"]
CATEGORIES: Final[tuple[Category, ...]] = ("bw", "cold", "warm", "cinematic")

Name = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$", max_length=40)]

REFERENCE: Final = re.compile(r"^\$([a-z][a-z0-9_]*)$")
"""A parameter reference in an operation: ``$`` and the parameter's name."""

_OPERATION: Final = TypeAdapter(AnyOperation)


class LookParameter(BaseModel):
    """A value a look exposes to the UI, as a slider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    default: float = Field(description="Value used unless the project sets another.")
    min: float = Field(description="Lowest value the slider allows.")
    max: float = Field(description="Highest value the slider allows.")
    label: str = Field(min_length=1, max_length=40, description="Shown in the UI.")

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not self.min <= self.default <= self.max:
            raise ValueError(
                f"needs min <= default <= max, got {self.min}, {self.default}, {self.max}"
            )
        return self


def _references(value: Any) -> set[str]:
    if isinstance(value, str):
        match = REFERENCE.match(value)
        return {match.group(1)} if match else set()
    if isinstance(value, Mapping):
        return set().union(*(_references(v) for v in value.values()))
    if isinstance(value, list | tuple):
        return set().union(*(_references(v) for v in value))
    return set()


def _substitute(value: Any, values: Mapping[str, float]) -> Any:
    if isinstance(value, str):
        match = REFERENCE.match(value)
        return values[match.group(1)] if match else value
    if isinstance(value, Mapping):
        return {key: _substitute(v, values) for key, v in value.items()}
    if isinstance(value, list | tuple):
        return [_substitute(v, values) for v in value]
    return value


class LookParameterError(ValueError):
    """Parameter values given for a look are unknown or out of range."""


class LookFile(BaseModel):
    """The contents of a look file, ``<category>/<name>.yaml``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = Field(default=1, description="Look file format version.")
    name: Name = Field(description="The look's name within its category, e.g. nordic.")
    category: Category = Field(description="bw, cold, warm or cinematic.")
    description: str = Field(min_length=1, max_length=200, description="One line, for people.")
    parameters: dict[Name, LookParameter] = Field(
        default_factory=dict, description="Values the UI exposes; operations use them as $name."
    )
    operations: list[dict[str, Any]] = Field(
        min_length=1,
        max_length=32,
        description="The steps, in order; numeric values may be $parameter references.",
    )

    @model_validator(mode="after")
    def _operations_valid(self) -> Self:
        used = set().union(*(_references(operation) for operation in self.operations))
        unknown = sorted(used - set(self.parameters))
        if unknown:
            raise ValueError(f"operations use undefined parameters: {', '.join(unknown)}")
        unused = sorted(set(self.parameters) - used)
        if unused:
            raise ValueError(f"parameters not used by any operation: {', '.join(unused)}")
        for which in ("default", "min", "max"):
            values = {name: getattr(p, which) for name, p in self.parameters.items()}
            for index, operation in enumerate(self.operations):
                try:
                    _OPERATION.validate_python(_substitute(operation, values))
                except ValueError as error:
                    detail = f" with parameters at their {which}" if used else ""
                    raise ValueError(f"operations[{index}] is invalid{detail}: {error}") from None
        return self

    @property
    def key(self) -> str:
        """``category/name``, how projects refer to the look."""
        return f"{self.category}/{self.name}"

    def resolve(self, values: Mapping[str, float] | None = None) -> list[Operation]:
        """The operations with parameter references replaced by ``values`` (or defaults).

        Raises LookParameterError for an unknown parameter or a value outside its range.
        """
        values = dict(values or {})
        unknown = sorted(set(values) - set(self.parameters))
        if unknown:
            known = ", ".join(sorted(self.parameters)) or "none"
            raise LookParameterError(
                f"{self.key} has no parameter {', '.join(unknown)} (its parameters: {known})"
            )
        resolved: dict[str, float] = {}
        for name, parameter in self.parameters.items():
            value = values.get(name, parameter.default)
            if not parameter.min <= value <= parameter.max:
                raise LookParameterError(
                    f"{self.key}: {name} must be between {parameter.min} and {parameter.max}, "
                    f"got {value}"
                )
            resolved[name] = value
        try:
            return [
                _OPERATION.validate_python(_substitute(operation, resolved))
                for operation in self.operations
            ]
        except ValidationError as error:
            raise LookParameterError(f"{self.key}: these parameter values give {error}") from None


class LookFileError(Exception):
    """A look file is unreadable or invalid, or a look doesn't exist. User-facing."""


@dataclass(frozen=True)
class Look:
    """A loaded look: its file's contents and the SHA-256 of its bytes (for sidecars)."""

    file: LookFile
    sha256: str

    @property
    def key(self) -> str:
        return self.file.key


def load_look_file(path: Path) -> Look:
    """Read and validate one look file. Raises LookFileError."""
    try:
        data = path.read_bytes()
    except OSError as error:
        raise LookFileError(f"cannot read look file {path}: {error}") from None
    try:
        content = yaml.safe_load(data)
    except yaml.YAMLError as error:
        raise LookFileError(f"{path.name} is not valid YAML: {error}") from None
    try:
        look = LookFile.model_validate(content)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in item['loc']) or '(top level)'}: {item['msg']}"
            for item in error.errors()
        )
        raise LookFileError(f"look file {path.name} is invalid: {problems}") from None
    return Look(file=look, sha256=hashlib.sha256(data).hexdigest())


BUILT_IN_LOOKS: Final = Path(__file__).parents[1] / "grade" / "looks"
"""Where the built-in look files are (package data, next to the grade stage's code; found
by path, since importing ``picturesq.grade`` from here would be circular)."""


def load_looks(directory: Path) -> dict[str, Look]:
    """Every ``<category>/<name>.yaml`` under ``directory``, keyed ``category/name``.

    A file's ``category`` and ``name`` must match its path. Raises LookFileError.
    """
    looks: dict[str, Look] = {}
    for category in CATEGORIES:
        for path in sorted((directory / category).glob("*.yaml")):
            look = load_look_file(path)
            expected = f"{category}/{path.stem}"
            if look.key != expected:
                raise LookFileError(
                    f"{category}/{path.name} says it is {look.key}; it must be {expected}"
                )
            looks[look.key] = look
    return looks


@cache
def look_library() -> dict[str, Look]:
    """The built-in looks, keyed ``category/name``, in category then name order."""
    return load_looks(BUILT_IN_LOOKS)


def find_look(key: str, library: Mapping[str, Look] | None = None) -> Look:
    """The look called ``key`` (``category/name``). Raises LookFileError naming the others."""
    library = look_library() if library is None else library
    look = library.get(key)
    if look is None:
        known = ", ".join(library) or "none"
        raise LookFileError(f"no look called {key!r} (available: {known})")
    return look
