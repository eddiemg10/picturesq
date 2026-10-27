"""JSON Schema export of the config models (`picturesq schema`)."""

import json
from typing import Any, Final

from pydantic import TypeAdapter

from picturesq.config.look import REFERENCE, LookFile
from picturesq.config.operations import AnyOperation
from picturesq.config.project import ProjectConfig

JSON_SCHEMA_DIALECT: Final = "https://json-schema.org/draft/2020-12/schema"


def project_schema() -> dict[str, Any]:
    """The JSON Schema of ``picturesq.yaml``, generated from ``ProjectConfig``."""
    return {"$schema": JSON_SCHEMA_DIALECT, **ProjectConfig.model_json_schema()}


_PARAMETER_REFERENCE: Final = {
    "type": "string",
    "pattern": REFERENCE.pattern,
    "description": "A parameter of this look, as $name.",
}


def _allow_references(node: Any) -> Any:
    """Let every number in an operation's schema also be a ``$parameter`` reference."""
    if isinstance(node, list):
        return [_allow_references(item) for item in node]
    if not isinstance(node, dict):
        return node
    node = {key: _allow_references(value) for key, value in node.items()}
    if node.get("type") in ("number", "integer"):
        return {"anyOf": [node, _PARAMETER_REFERENCE]}
    return node


def look_schema() -> dict[str, Any]:
    """The JSON Schema of a look file, generated from ``LookFile`` and the operation models.

    Each operation is described by its own model (chosen by ``op``); any of its numbers may
    instead be a ``$parameter`` reference.
    """
    schema = LookFile.model_json_schema()
    operation = TypeAdapter(AnyOperation).json_schema(ref_template="#/$defs/{model}")
    definitions = {
        name: _allow_references(definition)
        for name, definition in operation.pop("$defs", {}).items()
    }
    schema["$defs"] = {**schema.get("$defs", {}), **definitions}
    operations = schema["properties"]["operations"]
    operations["items"] = operation
    return {"$schema": JSON_SCHEMA_DIALECT, **schema}


def dump_schema(schema: dict[str, Any]) -> str:
    """Serialise a schema the way `picturesq schema` prints it (and docs/schema/ stores it)."""
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
