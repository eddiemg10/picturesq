"""`picturesq looks`."""

import json

from typer.testing import CliRunner

from picturesq.cli import app
from picturesq.config.look import Look

runner = CliRunner()


def test_lists_every_look_with_its_parameters(test_looks: dict[str, Look]) -> None:
    result = runner.invoke(app, ["looks"])
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0].startswith("bw/test_mono") and "red-filter" in lines[0]
    assert lines[1].startswith("cold/test_cool")
    assert "fade: Fade, 0.0 to 0.2 (default 0.05)" in lines[2]


def test_json_contract(test_looks: dict[str, Look]) -> None:
    result = runner.invoke(app, ["looks", "--json"])
    assert result.exit_code == 0, result.output
    document = json.loads(result.stdout)
    assert [look["look"] for look in document["looks"]] == ["bw/test_mono", "cold/test_cool"]
    cool = document["looks"][1]
    assert cool == {
        "look": "cold/test_cool",
        "category": "cold",
        "name": "test_cool",
        "description": "A test look: cooler, more contrast, faded",
        "parameters": {"fade": {"default": 0.05, "min": 0.0, "max": 0.2, "label": "Fade"}},
        "operations": ["white_balance", "contrast", "fade"],
    }


def test_category_filter(test_looks: dict[str, Look]) -> None:
    result = runner.invoke(app, ["looks", "--category", "bw", "--json"])
    assert [look["look"] for look in json.loads(result.stdout)["looks"]] == ["bw/test_mono"]
    empty = runner.invoke(app, ["looks", "--category", "warm"])
    assert empty.exit_code == 0 and empty.stdout.strip() == "no looks in warm"


def test_unknown_category_is_a_usage_error() -> None:
    assert runner.invoke(app, ["looks", "--category", "pastel"]).exit_code == 2


def test_the_built_in_library_lists() -> None:
    assert runner.invoke(app, ["looks", "--json"]).exit_code == 0
