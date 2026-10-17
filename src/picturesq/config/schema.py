"""JSON Schema export of the config models (`picturesq schema`)."""

import json
from typing import Any, Final

from picturesq.config.project import ProjectConfig

JSON_SCHEMA_DIALECT: Final = "https://json-schema.org/draft/2020-12/schema"


def project_schema() -> dict[str, Any]:
    """The JSON Schema of ``picturesq.yaml``, generated from ``ProjectConfig``."""
    return {"$schema": JSON_SCHEMA_DIALECT, **ProjectConfig.model_json_schema()}


def dump_schema(schema: dict[str, Any]) -> str:
    """Serialise a schema the way `picturesq schema` prints it (and docs/schema/ stores it)."""
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
