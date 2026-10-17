from typer.testing import CliRunner

from picturesq import __version__
from picturesq.cli import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help_lists_all_verbs() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for verb in [
        "run",
        "decode",
        "normalise",
        "preview",
        "looks",
        "ui",
        "export",
        "schema",
        "doctor",
    ]:
        assert verb in result.output


def test_unimplemented_command_fails_cleanly() -> None:
    result = runner.invoke(app, ["normalise", "."])
    assert result.exit_code == 1
