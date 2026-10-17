"""`picturesq doctor`: pure checks, terminal graphics heuristic, CLI output and exit codes."""

import json
import sys
from collections.abc import Iterator
from dataclasses import replace

import pytest
from typer.testing import CliRunner

from picturesq import parallel
from picturesq.cli import app
from picturesq.cli.doctor import (
    LIBRARIES,
    Check,
    Environment,
    Status,
    build_checks,
    detect_terminal_graphics,
    render_json,
    render_text,
)
from picturesq.hardware import Hardware

runner = CliRunner()
# The module, not the `doctor` command that shadows it as an attribute of picturesq.cli.
doctor_module = sys.modules["picturesq.cli.doctor"]


@pytest.fixture(autouse=True)
def _restore_parallelism() -> Iterator[None]:
    """The root callback sets process-wide parallelism; put it back after each test."""
    with parallel.using(parallel.current()):
        yield


def _environment(**changes: object) -> Environment:
    hardware = Hardware(logical_cpus=8, physical_cores=4, cache_per_core=3 << 19)
    automatic = parallel.auto(hardware=hardware)
    env = Environment(
        picturesq="0.0.1",
        python=(3, 12, 3),
        platform="Linux x86_64",
        platform_release="6.1",
        libraw=(0, 22, 1),
        libraw_flags={"DNGDEFLATECODEC": True, "DNGLOSSYCODEC": True, "OPENMP": True},
        libraries=dict.fromkeys(LIBRARIES, "1.0"),
        pillow_features={"jpg": True, "littlecms2": True},
        hardware=hardware,
        parallelism=automatic,
        automatic=automatic,
        threads_source=None,
        block_source=None,
        terminal=detect_terminal_graphics({"TERM": "xterm-kitty"}),
    )
    return replace(env, **changes)  # type: ignore[arg-type]


def _by_id(checks: list[Check]) -> dict[str, Check]:
    return {check.check: check for check in checks}


def test_healthy_environment_is_all_ok() -> None:
    checks = build_checks(_environment())
    assert {c.status for c in checks} == {Status.ok}
    ids = [c.check for c in checks]
    assert len(ids) == len(set(ids))


def test_threads_explain_hyperthreads() -> None:
    threads = _by_id(build_checks(_environment()))["threads"]
    assert threads.value == "4 per photo"
    assert "one per physical core" in threads.message
    assert "8 logical CPUs include hyperthreads" in threads.message


def test_block_size_from_cache() -> None:
    block = _by_id(build_checks(_environment()))["block_size"]
    assert block.value == "64k pixels"
    assert "1.5 MiB" in block.message


def test_overrides_are_reported_with_the_automatic_choice() -> None:
    env = _environment(
        parallelism=parallel.Parallelism(threads=16, block_pixels=1 << 17),
        threads_source="--threads",
        block_source="PICTURESQ_BLOCK_PIXELS",
    )
    checks = _by_id(build_checks(env))
    assert checks["threads"].status is Status.warning  # more than the 8 usable CPUs
    assert "set by --threads (automatic: 4)" in checks["threads"].message
    assert checks["block_size"].message == "set by PICTURESQ_BLOCK_PIXELS (automatic: 64k pixels)"


def test_unknown_hardware_warns() -> None:
    hardware = Hardware(logical_cpus=2, physical_cores=None, cache_per_core=None)
    automatic = parallel.auto(hardware=hardware)
    checks = _by_id(
        build_checks(_environment(hardware=hardware, parallelism=automatic, automatic=automatic))
    )
    for check in ("cpus", "cache", "threads", "block_size"):
        assert checks[check].status is Status.warning, check


def test_old_libraw_and_missing_pieces_are_errors() -> None:
    env = _environment(
        libraw=(0, 20, 2),
        python=(3, 10, 0),
        libraries={**dict.fromkeys(LIBRARIES, "1.0"), "tifffile": None},
        pillow_features={"jpg": True, "littlecms2": False},
    )
    checks = _by_id(build_checks(env))
    for check in ("libraw", "python", "tifffile", "pillow_features"):
        assert checks[check].status is Status.error, check


def test_missing_libraw_feature_warns() -> None:
    env = _environment(libraw_flags={"DNGDEFLATECODEC": False, "DNGLOSSYCODEC": True})
    check = _by_id(build_checks(env))["libraw_features"]
    assert check.status is Status.warning
    assert check.value == "missing DNG deflate"


def test_unreported_libraw_features_are_not_a_problem() -> None:
    check = _by_id(build_checks(_environment(libraw_flags=None)))["libraw_features"]
    assert check.status is Status.ok
    assert check.value == "unknown"


@pytest.mark.parametrize(
    ("env", "summary"),
    [
        ({"TERM": "xterm-kitty"}, "kitty"),
        ({"TERM": "xterm-256color", "KITTY_WINDOW_ID": "1"}, "kitty"),
        ({"TERM_PROGRAM": "WezTerm"}, "kitty"),
        ({"TERM_PROGRAM": "ghostty"}, "kitty"),
        ({"TERM_PROGRAM": "iTerm.app"}, "sixel (likely)"),
        ({"TERM": "foot"}, "sixel (likely)"),
        ({"TERM": "xterm-256color", "WT_SESSION": "abc"}, "sixel (likely)"),
        ({"KONSOLE_VERSION": "230805"}, "sixel"),
        ({"KONSOLE_VERSION": "210800"}, "none detected"),
        ({"TERM_PROGRAM": "vscode"}, "none detected"),
        ({"TERM_PROGRAM": "Apple_Terminal"}, "none detected"),
        ({"TERM": "xterm-256color"}, "none detected"),
        ({}, "none detected"),
    ],
)
def test_terminal_graphics_heuristic(env: dict[str, str], summary: str) -> None:
    assert detect_terminal_graphics(env).summary == summary


def test_terminal_graphics_notes_multiplexer() -> None:
    graphics = detect_terminal_graphics({"TERM": "screen-256color", "TMUX": "/tmp/x,1,0"})
    assert graphics.multiplexer == "tmux"
    check = _by_id(build_checks(_environment(terminal=graphics)))["terminal_graphics"]
    assert check.status is Status.warning
    assert "passthrough" in check.message
    assert "guess" in check.message


def test_render_text_aligns_columns() -> None:
    lines = render_text(build_checks(_environment())).splitlines()
    assert lines[0].index("0.0.1") == lines[1].index("3.12.3")
    assert lines[-1] == "0 error(s), 0 warning(s)"


def test_render_json_document() -> None:
    document = json.loads(render_json(build_checks(_environment())))
    assert set(document) == {"checks", "summary"}
    assert set(document["checks"][0]) == {"check", "status", "value", "message", "data"}
    assert document["summary"] == {"ok": len(document["checks"]), "warning": 0, "error": 0}


def test_cli_text_and_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor_module, "gather", lambda ctx: _environment())
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "Terminal graphics" in result.output


def test_cli_json_and_error_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor_module, "gather", lambda ctx: _environment(libraw=(0, 19)))
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 1
    document = json.loads(result.stdout)
    assert document["summary"]["error"] == 1


def test_cli_real_environment_reports_overrides() -> None:
    result = runner.invoke(
        app, ["--threads", "3", "doctor", "--json"], env={"PICTURESQ_BLOCK_PIXELS": "8192"}
    )
    assert result.exit_code == 0, result.output
    checks = {c["check"]: c for c in json.loads(result.stdout)["checks"]}
    assert checks["threads"]["data"]["threads"] == 3
    assert checks["threads"]["data"]["source"] == "--threads"
    assert checks["block_size"]["data"] == {
        "block_pixels": 8192,
        "automatic": checks["block_size"]["data"]["automatic"],
        "source": "PICTURESQ_BLOCK_PIXELS",
    }
