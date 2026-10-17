"""`picturesq schema` and the committed docs/schema/picturesq.schema.json."""

import json
import re
from pathlib import Path

import jsonschema
import pytest
import yaml
from typer.testing import CliRunner

from picturesq.cli import app
from picturesq.config import ProjectConfig, dump_project_config, dump_schema, project_schema

COMMITTED = Path(__file__).parents[2] / "docs" / "schema" / "picturesq.schema.json"
DOC = Path(__file__).parents[2] / "docs" / "configuration.md"


def test_schema_is_valid_json_schema() -> None:
    jsonschema.Draft202012Validator.check_schema(project_schema())


def test_cli_prints_the_schema() -> None:
    result = CliRunner().invoke(app, ["schema"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == project_schema()
    assert CliRunner().invoke(app, ["schema", "project"]).stdout == result.stdout


def test_cli_rejects_unknown_kind() -> None:
    assert CliRunner().invoke(app, ["schema", "nope"]).exit_code == 2


def test_committed_schema_is_current() -> None:
    assert COMMITTED.read_text(encoding="utf-8") == dump_schema(project_schema()), (
        "regenerate with: uv run picturesq schema > docs/schema/picturesq.schema.json"
    )


def test_defaults_validate() -> None:
    data = yaml.safe_load(dump_project_config(ProjectConfig()))
    jsonschema.validate(data, project_schema())


def _examples() -> list[str]:
    body = DOC.read_text(encoding="utf-8").split("\n## Examples\n", 1)[1].split("\n## ", 1)[0]
    return re.findall(r"```yaml\n(.*?)```", body, flags=re.DOTALL)


@pytest.mark.parametrize("block", _examples())
def test_documented_examples_validate(block: str) -> None:
    jsonschema.validate(yaml.safe_load(block), project_schema())


@pytest.mark.parametrize(
    "data",
    [
        {"decode": {"demosaic": "magic"}},
        {"export": {"outputs": {"web": {"quality": 101}}}},
        {"unknown_section": {}},
    ],
)
def test_schema_rejects_what_the_models_reject(data: dict[str, object]) -> None:
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(data, project_schema())
