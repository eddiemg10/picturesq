"""`picturesq skill`."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from picturesq.cli import app
from picturesq.cli.skill import skill_text

runner = CliRunner()


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    return home


def test_the_skill_ships_in_the_package() -> None:
    text = skill_text()
    assert text.startswith("---\nname: picturesq\n")
    assert "description:" in text.split("---")[1]


def test_show_prints_the_skill() -> None:
    result = runner.invoke(app, ["skill", "show"])
    assert result.exit_code == 0, result.output
    assert result.stdout == skill_text()


def test_show_survives_a_stdout_that_is_not_utf8() -> None:
    # Piped on Windows, stdout is cp1252, which lacks the skill's minus sign (U+2212).
    env = os.environ | {"PYTHONIOENCODING": "cp1252"}
    result = subprocess.run(
        [sys.executable, "-m", "picturesq", "skill", "show"], capture_output=True, env=env
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.decode("utf-8") == skill_text()


def test_install_for_claude_code_in_the_home_folder(home: Path) -> None:
    result = runner.invoke(app, ["skill", "install"])
    assert result.exit_code == 0, result.output
    target = home / ".claude" / "skills" / "picturesq" / "SKILL.md"
    assert target.read_text(encoding="utf-8") == skill_text()


def test_install_for_one_project(tmp_path: Path, home: Path) -> None:
    result = runner.invoke(app, ["skill", "install", "--project", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".claude" / "skills" / "picturesq" / "SKILL.md").is_file()
    assert not (home / ".claude").exists()


def test_install_into_another_agents_skills_folder(tmp_path: Path) -> None:
    result = runner.invoke(app, ["skill", "install", "--dir", str(tmp_path / "skills")])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "skills" / "picturesq" / "SKILL.md").is_file()


def test_reinstalling_the_same_skill_is_a_no_op(home: Path) -> None:
    runner.invoke(app, ["skill", "install"])
    result = runner.invoke(app, ["skill", "install"])
    assert result.exit_code == 0, result.output
    assert "already up to date" in result.stdout


def test_a_different_skill_is_replaced_only_with_force(home: Path) -> None:
    target = home / ".claude" / "skills" / "picturesq" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("my own notes\n", encoding="utf-8")
    refused = runner.invoke(app, ["skill", "install"])
    assert refused.exit_code == 1
    assert "--force" in refused.output
    assert target.read_text(encoding="utf-8") == "my own notes\n"
    forced = runner.invoke(app, ["skill", "install", "--force"])
    assert forced.exit_code == 0, forced.output
    assert target.read_text(encoding="utf-8") == skill_text()


def test_project_and_dir_together_are_refused(tmp_path: Path) -> None:
    result = runner.invoke(app, ["skill", "install", "--project", str(tmp_path), "--dir", "x"])
    assert result.exit_code == 2


def test_project_must_be_a_folder(tmp_path: Path) -> None:
    result = runner.invoke(app, ["skill", "install", "--project", str(tmp_path / "missing")])
    assert result.exit_code == 2
