"""`picturesq skill`: the agent skill that ships in the package, for coding agents to use."""

from importlib.resources import files
from pathlib import Path
from typing import Annotated

import typer

from picturesq.cli.config import EXIT_ERROR, EXIT_INVALID, fail

SKILL_NAME = "picturesq"
SKILL_FILENAME = "SKILL.md"

skill_app = typer.Typer(
    name="skill",
    help="The agent skill: teaches a coding agent (Claude Code, Codex, …) to use picturesq.",
    no_args_is_help=True,
)


def skill_text() -> str:
    """The skill as shipped with this version of picturesq."""
    return (files("picturesq") / "skill" / SKILL_FILENAME).read_text(encoding="utf-8")


def skill_target(project: Path | None, directory: Path | None) -> Path:
    """Where ``install`` writes: a skills folder's ``picturesq/SKILL.md``.

    Claude Code reads user skills from ``~/.claude/skills`` and a project's from
    ``<project>/.claude/skills``; ``directory`` is any other agent's skills folder.
    """
    if directory is not None:
        skills = directory
    elif project is not None:
        skills = project / ".claude" / "skills"
    else:
        skills = Path.home() / ".claude" / "skills"
    return skills / SKILL_NAME / SKILL_FILENAME


@skill_app.command()
def show() -> None:
    """Print the skill (to paste into AGENTS.md or another agent's instructions)."""
    typer.echo(skill_text(), nl=False)


@skill_app.command()
def install(
    project: Annotated[
        Path | None,
        typer.Option(
            "--project",
            help="Install for one project only: <project>/.claude/skills (Claude Code).",
        ),
    ] = None,
    directory: Annotated[
        Path | None,
        typer.Option("--dir", help="Install into this skills folder (another agent's)."),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Replace a different SKILL.md already there.")
    ] = False,
) -> None:
    """Install the skill for Claude Code (default: every project, ~/.claude/skills)."""
    if project is not None and directory is not None:
        raise fail("give --project or --dir, not both", EXIT_INVALID)
    if project is not None and not project.is_dir():
        raise fail(f"{project} is not a folder", EXIT_INVALID)
    target = skill_target(project, directory)
    text = skill_text()
    if target.is_file():
        if target.read_text(encoding="utf-8") == text:
            typer.echo(f"{target} is already up to date")
            return
        if not force:
            raise fail(
                f"{target} exists and differs (an older picturesq, or edited by hand); "
                "rerun with --force to replace it",
                EXIT_ERROR,
            )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")
    typer.echo(f"installed the picturesq skill: {target}")
