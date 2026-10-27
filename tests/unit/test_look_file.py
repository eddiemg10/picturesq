"""Look files: validation, parameter references, loading and the look library."""

import hashlib
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import jsonschema
import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from picturesq.cli import app
from picturesq.config import (
    CATEGORIES,
    LookFile,
    LookFileError,
    LookParameterError,
    dump_schema,
    find_look,
    load_look_file,
    load_looks,
    look_library,
    look_schema,
)
from picturesq.config.look import BUILT_IN_LOOKS
from picturesq.config.operations import (
    OPERATION_TYPES,
    ContrastOperation,
    FadeOperation,
    SplitToneOperation,
)

ROOT = Path(__file__).parents[2]
DOC = ROOT / "docs" / "configuration.md"
COMMITTED = ROOT / "docs" / "schema" / "look.schema.json"

NORDIC = {
    "version": 1,
    "name": "nordic",
    "category": "cold",
    "description": "Muted, cool shadows",
    "parameters": {
        "shadow_tint": {"default": 0.3, "min": 0.0, "max": 0.8, "label": "Shadow tint"},
        "fade": {"default": 0.04, "min": 0.0, "max": 0.12, "label": "Fade"},
    },
    "operations": [
        {"op": "contrast", "amount": 0.12},
        {"op": "split_tone", "shadows": {"hue": 230, "amount": "$shadow_tint"}},
        {"op": "fade", "amount": "$fade"},
    ],
}


def _look(**changes: object) -> dict[str, object]:
    return {**NORDIC, **changes}


def test_valid_look_resolves_to_operations() -> None:
    look = LookFile.model_validate(NORDIC)
    assert look.key == "cold/nordic"
    contrast, split, fade = look.resolve()
    assert contrast == ContrastOperation(amount=0.12)
    assert isinstance(split, SplitToneOperation) and split.shadows.amount == 0.3
    assert fade == FadeOperation(amount=0.04)


def test_resolve_uses_given_values() -> None:
    _, split, fade = LookFile.model_validate(NORDIC).resolve({"shadow_tint": 0.5})
    assert isinstance(split, SplitToneOperation) and split.shadows.amount == 0.5
    assert fade == FadeOperation(amount=0.04)


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"shadow": 0.1}, "has no parameter shadow"),
        ({"fade": 0.5}, "fade must be between 0.0 and 0.12"),
    ],
)
def test_resolve_rejects_bad_values(values: dict[str, float], message: str) -> None:
    with pytest.raises(LookParameterError, match=message):
        LookFile.model_validate(NORDIC).resolve(values)


FADE = {"fade": {"default": 0.04, "min": 0.0, "max": 0.12, "label": "Fade"}}


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"parameters": FADE, "operations": [{"op": "fade", "amount": "$missing"}]},
            "undefined parameters: missing",
        ),
        (
            {"parameters": FADE, "operations": [{"op": "contrast", "amount": 0.1}]},
            "not used by any operation: fade",
        ),
        (
            {"parameters": {}, "operations": [{"op": "sharpen"}]},
            "does not match any of the expected tags",
        ),
        ({"parameters": {}, "operations": [{"op": "fade", "colour": 1}]}, "Extra inputs"),
        ({"parameters": {}, "operations": []}, "at least 1 item"),
        ({"category": "pastel"}, "Input should be 'bw', 'cold', 'warm' or 'cinematic'"),
        ({"name": "Nordic"}, "should match pattern"),
    ],
)
def test_invalid_look_files(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=re.escape(message)):
        LookFile.model_validate(_look(**changes))


def test_operations_are_checked_with_parameters_at_their_range() -> None:
    """A parameter whose max takes an operation out of its range is an error."""
    parameters = {"fade": {"default": 0.04, "min": 0.0, "max": 0.5, "label": "Fade"}}
    look = _look(parameters=parameters, operations=[{"op": "fade", "amount": "$fade"}])
    with pytest.raises(ValidationError, match="with parameters at their max"):
        LookFile.model_validate(look)


def test_parameter_default_inside_its_range() -> None:
    parameters = {"fade": {"default": 0.2, "min": 0.0, "max": 0.1, "label": "Fade"}}
    with pytest.raises(ValidationError, match="min <= default <= max"):
        LookFile.model_validate(
            _look(parameters=parameters, operations=[{"op": "fade", "amount": "$fade"}])
        )


def test_references_work_inside_lists() -> None:
    parameters = {"top": {"default": 1.5, "min": 1.0, "max": 2.0, "label": "Highlights"}}
    look = LookFile.model_validate(
        _look(
            parameters=parameters,
            operations=[{"op": "tone_curve", "points": [[0, 0], [2, "$top"]]}],
        )
    )
    (curve,) = look.resolve({"top": 1.2})
    assert curve.points == ((0.0, 0.0), (2.0, 1.2))  # type: ignore[attr-defined]


def test_resolve_validates_combinations() -> None:
    """Each parameter alone at its ends is fine, but together they can break a curve."""
    parameters = {
        "a": {"default": 1.0, "min": 0.5, "max": 1.5, "label": "A"},
        "b": {"default": 1.6, "min": 1.0, "max": 2.0, "label": "B"},
    }
    look = LookFile.model_validate(
        _look(
            parameters=parameters,
            operations=[{"op": "tone_curve", "points": [[0, 0], [1, "$a"], [2, "$b"]]}],
        )
    )
    with pytest.raises(LookParameterError, match="must not decrease"):
        look.resolve({"a": 1.5, "b": 1.0})


def _write(directory: Path, relative: str, content: dict[str, object]) -> Path:
    path = directory / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(content), encoding="utf-8")
    return path


def test_load_look_file_and_its_hash(tmp_path: Path) -> None:
    path = _write(tmp_path, "cold/nordic.yaml", NORDIC)
    look = load_look_file(path)
    assert look.key == "cold/nordic"

    assert look.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


def test_load_look_file_errors(tmp_path: Path) -> None:
    broken = tmp_path / "broken.yaml"
    broken.write_text("name: [", encoding="utf-8")
    with pytest.raises(LookFileError, match="not valid YAML"):
        load_look_file(broken)
    invalid = _write(tmp_path, "invalid.yaml", _look(category="pastel"))
    with pytest.raises(LookFileError, match="invalid: category"):
        load_look_file(invalid)
    with pytest.raises(LookFileError, match="cannot read"):
        load_look_file(tmp_path / "missing.yaml")


def test_load_looks_keys_and_order(tmp_path: Path) -> None:
    _write(tmp_path, "cold/nordic.yaml", NORDIC)
    _write(tmp_path, "cold/frost.yaml", _look(name="frost"))
    _write(tmp_path, "bw/silver.yaml", _look(name="silver", category="bw"))
    _write(tmp_path, "other/ignored.yaml", NORDIC)
    assert list(load_looks(tmp_path)) == ["bw/silver", "cold/frost", "cold/nordic"]


def test_load_looks_checks_the_path(tmp_path: Path) -> None:
    _write(tmp_path, "warm/nordic.yaml", NORDIC)
    with pytest.raises(LookFileError, match="says it is cold/nordic; it must be warm/nordic"):
        load_looks(tmp_path)


def test_find_look(tmp_path: Path) -> None:
    _write(tmp_path, "cold/nordic.yaml", NORDIC)
    library = load_looks(tmp_path)
    assert find_look("cold/nordic", library).key == "cold/nordic"
    with pytest.raises(
        LookFileError, match=r"no look called 'cold/frost' \(available: cold/nordic\)"
    ):
        find_look("cold/frost", library)


def test_built_in_looks_load() -> None:
    library = look_library()
    for key, look in library.items():
        assert key == look.key
        look.file.resolve()
    assert all(path.parent.name in CATEGORIES for path in BUILT_IN_LOOKS.glob("*/*.yaml"))


def test_look_schema_is_valid_json_schema() -> None:
    jsonschema.Draft202012Validator.check_schema(look_schema())


def test_look_schema_accepts_looks_and_references_only_as_numbers() -> None:
    schema = look_schema()
    jsonschema.validate(NORDIC, schema)
    for path in BUILT_IN_LOOKS.glob("*/*.yaml"):
        jsonschema.validate(yaml.safe_load(path.read_text(encoding="utf-8")), schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_look(operations=[{"op": "fade", "amount": "fade"}]), schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_look(operations=[{"op": "sharpen"}]), schema)


def test_cli_prints_the_look_schema() -> None:
    result = CliRunner().invoke(app, ["schema", "look"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == look_schema()


def test_committed_look_schema_is_current() -> None:
    assert COMMITTED.read_text(encoding="utf-8") == dump_schema(look_schema()), (
        "regenerate with: uv run picturesq schema look > docs/schema/look.schema.json"
    )


def _doc_section(heading: str) -> str:
    text = DOC.read_text(encoding="utf-8")
    return text.split(f"\n{heading}\n", 1)[1].split("\n## ", 1)[0]


def test_documented_look_file_is_valid() -> None:
    (block,) = re.findall(r"```yaml\n(.*?)```", _doc_section("## Look files"), flags=re.DOTALL)
    LookFile.model_validate(yaml.safe_load(block))


@pytest.mark.parametrize("operation_type", OPERATION_TYPES, ids=lambda t: t.__name__)
def test_every_operation_key_is_documented(operation_type: type) -> None:
    name = operation_type.model_fields["op"].default
    space = "display" if operation_type.space == "display" else "scene"
    text = DOC.read_text(encoding="utf-8")
    heading = f"#### `{name}` ({space})"
    assert heading in text, f"{heading} is missing from docs/configuration.md"
    section = text.split(heading, 1)[1].split("\n#### ", 1)[0]
    for field in operation_type.model_fields:
        if field != "op":
            assert f"| `{field}` |" in section, f"{name}.{field} is not documented"


@pytest.mark.slow
def test_wheel_contains_the_built_in_looks(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("needs uv on PATH")
    subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    (wheel,) = tmp_path.glob("*.whl")
    names = set(zipfile.ZipFile(wheel).namelist())
    for path in BUILT_IN_LOOKS.glob("*/*.yaml"):
        assert f"picturesq/grade/looks/{path.parent.name}/{path.name}" in names
