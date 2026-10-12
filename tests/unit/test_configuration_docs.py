"""docs/configuration.md must match the config models."""

import re
from pathlib import Path

import pytest
import yaml

from picturesq.config import (
    DecodeConfig,
    ExportConfig,
    OutputConfig,
    ProjectConfig,
    dump_project_config,
)

DOC = Path(__file__).parents[2] / "docs" / "configuration.md"


def _yaml_blocks(section: str) -> list[str]:
    text = DOC.read_text(encoding="utf-8")
    body = text.split(f"\n## {section}\n", 1)[1].split("\n## ", 1)[0]
    return re.findall(r"```yaml\n(.*?)```", body, flags=re.DOTALL)


def test_documented_defaults_are_the_defaults() -> None:
    (defaults,) = _yaml_blocks("Defaults")
    assert defaults == dump_project_config(ProjectConfig())


@pytest.mark.parametrize("block", _yaml_blocks("Examples"))
def test_examples_are_valid(block: str) -> None:
    ProjectConfig.model_validate(yaml.safe_load(block))


@pytest.mark.parametrize("model", [ProjectConfig, DecodeConfig, ExportConfig, OutputConfig])
def test_reference_lists_every_key(model: type[ProjectConfig]) -> None:
    text = DOC.read_text(encoding="utf-8")
    for name in model.model_fields:
        assert f"| `{name}` |" in text, f"{model.__name__}.{name} is not documented"
