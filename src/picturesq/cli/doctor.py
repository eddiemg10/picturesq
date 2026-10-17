"""`picturesq doctor`: report the environment and flag problems.

The checks are pure functions of an :class:`Environment` (``build_checks``), so tests can
feed any machine they like; ``gather`` is the only part that reads the real one.
"""

from __future__ import annotations

import json
import os
import platform
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from importlib import metadata
from typing import Any, Protocol

import typer

from picturesq import __version__, parallel
from picturesq.cli.config import EXIT_ERROR
from picturesq.hardware import Hardware, detect
from picturesq.parallel import (
    CACHE_BYTES_PER_BLOCK_PIXEL,
    MAX_BLOCK_PIXELS,
    MIN_BLOCK_PIXELS,
    Parallelism,
)

MIN_PYTHON = (3, 11)
MIN_LIBRAW = (0, 21)
"""Oldest LibRaw tested (``tests/unit/test_dependencies.py``)."""

LIBRARIES = ("rawpy", "numpy", "pillow", "tifffile", "pydantic")
"""Distributions whose versions are reported (LibRaw is reported separately)."""

LIBRAW_FEATURES = {
    "DNGDEFLATECODEC": ("DNG deflate", "deflate-compressed DNGs (e.g. floating-point HDR merges)"),
    "DNGLOSSYCODEC": ("DNG lossy", "lossy (JPEG-compressed) DNGs"),
}
"""LibRaw build features we rely on, as rawpy reports them in ``rawpy.flags``."""

PILLOW_FEATURES = {
    "jpg": "JPEG export",
    "littlecms2": "the sRGB colour profile embedded in every JPEG",
}


class Status(StrEnum):
    ok = "ok"
    warning = "warning"
    error = "error"


@dataclass(frozen=True)
class Check:
    check: str
    """Stable identifier (the JSON key agents match on)."""
    label: str
    status: Status
    value: str
    message: str = ""
    data: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class TerminalGraphics:
    """What the terminal can probably draw; a guess from environment variables."""

    protocol: str | None
    """``"kitty"``, ``"sixel"`` or None."""
    certain: bool
    """False when the terminal usually supports it but its version or settings can't be seen."""
    terminal: str | None
    reason: str
    multiplexer: str | None = None
    tty: bool = True

    @property
    def summary(self) -> str:
        if self.protocol is None:
            return "none detected"
        return self.protocol if self.certain else f"{self.protocol} (likely)"


@dataclass(frozen=True)
class Environment:
    """Everything the checks look at."""

    picturesq: str
    python: tuple[int, int, int]
    platform: str
    platform_release: str
    libraw: tuple[int, ...]
    libraw_flags: Mapping[str, bool] | None
    """None when this rawpy doesn't report LibRaw's build features."""
    libraries: Mapping[str, str | None]
    pillow_features: Mapping[str, bool]
    hardware: Hardware
    parallelism: Parallelism
    """What this run uses (after ``--threads``/``--block-pixels`` and their env variables)."""
    automatic: Parallelism
    """What ``parallel.auto()`` chooses with no overrides."""
    threads_source: str | None
    """The flag or env variable that set the threads, or None when chosen automatically."""
    block_source: str | None
    terminal: TerminalGraphics


# Terminal graphics -------------------------------------------------------------------------

_SIXEL_TERMS = {"foot", "foot-extra", "mlterm", "yaft-256color", "contour"}
_KONSOLE_SIXEL = 220400
"""Konsole 22.04 added sixel; ``KONSOLE_VERSION`` is e.g. ``"230805"``."""


def detect_terminal_graphics(env: Mapping[str, str], *, tty: bool = True) -> TerminalGraphics:
    """Guess the terminal's image protocol from its environment variables.

    A heuristic: terminals don't advertise graphics support in the environment, so this
    recognises the terminals known to have it. Asking the terminal directly (an escape
    sequence and a reply) would be exact, but needs an interactive terminal; M3 may add it.
    """
    term = env.get("TERM", "")
    program = env.get("TERM_PROGRAM", "")
    multiplexer = (
        "tmux"
        if "TMUX" in env or program == "tmux"
        else ("screen" if term.startswith("screen") or "STY" in env else None)
    )

    def found(
        protocol: str | None, terminal: str | None, reason: str, *, certain: bool = True
    ) -> TerminalGraphics:
        return TerminalGraphics(protocol, certain, terminal, reason, multiplexer, tty)

    if "KITTY_WINDOW_ID" in env or term == "xterm-kitty":
        return found("kitty", "kitty", "kitty terminal")
    if program == "ghostty" or term == "xterm-ghostty" or "GHOSTTY_RESOURCES_DIR" in env:
        return found("kitty", "Ghostty", "Ghostty supports the kitty protocol")
    if program == "WezTerm":
        return found("kitty", "WezTerm", "WezTerm supports the kitty protocol and sixel")
    if program == "iTerm.app":
        return found("sixel", "iTerm2", "iTerm2 3.3 or newer supports sixel", certain=False)
    if "KONSOLE_VERSION" in env:
        version = env["KONSOLE_VERSION"]
        if version.isdigit() and int(version) >= _KONSOLE_SIXEL:
            return found("sixel", "Konsole", "Konsole 22.04 or newer supports sixel")
        return found(None, "Konsole", "Konsole older than 22.04 has no sixel")
    if term in _SIXEL_TERMS or "sixel" in term:
        return found("sixel", term, f"TERM={term} supports sixel", certain=False)
    if "WT_SESSION" in env:
        return found(
            "sixel",
            "Windows Terminal",
            "Windows Terminal 1.22 or newer supports sixel (version not visible)",
            certain=False,
        )
    if program == "vscode":
        return found(
            None, "VS Code", "VS Code draws sixel only with terminal.integrated.enableImages on"
        )
    if program == "Apple_Terminal":
        return found(None, "Terminal.app", "macOS Terminal has no image protocol")
    return found(None, program or term or None, "no known graphics terminal in TERM/TERM_PROGRAM")


# Checks ------------------------------------------------------------------------------------


def _version(parts: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in parts)


def _bytes(size: int) -> str:
    for unit, shift in (("MiB", 20), ("KiB", 10)):
        if size >= 1 << shift:
            return f"{size / (1 << shift):.3g} {unit}"
    return f"{size} B"


def _pixels(count: int) -> str:
    return f"{count // 1024}k pixels" if count % 1024 == 0 else f"{count} pixels"


def _python(env: Environment) -> Check:
    version = _version(env.python)
    if env.python[:2] < MIN_PYTHON:
        return Check(
            "python", "Python", Status.error, version, f"needs {_version(MIN_PYTHON)} or newer"
        )
    return Check("python", "Python", Status.ok, version)


def _libraw(env: Environment) -> Check:
    version = _version(env.libraw)
    if env.libraw[: len(MIN_LIBRAW)] < MIN_LIBRAW:
        return Check(
            "libraw",
            "LibRaw",
            Status.error,
            version,
            f"needs {_version(MIN_LIBRAW)} or newer; upgrade rawpy",
        )
    return Check("libraw", "LibRaw", Status.ok, version, "via rawpy")


def _libraw_features(env: Environment) -> Check:
    flags = env.libraw_flags
    label = "LibRaw features"
    if flags is None:
        return Check(
            "libraw_features", label, Status.ok, "unknown", "this rawpy doesn't report them"
        )
    data = dict(flags)
    missing = [name for name in LIBRAW_FEATURES if not flags.get(name, False)]
    if missing:
        what = "; ".join(LIBRAW_FEATURES[name][1] for name in missing)
        return Check(
            "libraw_features",
            label,
            Status.warning,
            "missing " + ", ".join(LIBRAW_FEATURES[name][0] for name in missing),
            f"can't decode {what}",
            data,
        )
    openmp = "with OpenMP" if flags.get("OPENMP") else "without OpenMP (decode uses one core)"
    return Check(
        "libraw_features",
        label,
        Status.ok,
        ", ".join(short for short, _ in LIBRAW_FEATURES.values()),
        f"built {openmp}",
        data,
    )


def _library(name: str, version: str | None) -> Check:
    if version is None:
        return Check(name, name, Status.error, "missing", "reinstall picturesq")
    return Check(name, name, Status.ok, version)


def _pillow_features(env: Environment) -> Check:
    missing = [name for name in PILLOW_FEATURES if not env.pillow_features.get(name, False)]
    data = dict(env.pillow_features)
    if missing:
        what = "; ".join(PILLOW_FEATURES[name] for name in missing)
        return Check(
            "pillow_features",
            "Pillow features",
            Status.error,
            "missing " + ", ".join(missing),
            f"needed for {what}",
            data,
        )
    return Check(
        "pillow_features", "Pillow features", Status.ok, ", ".join(PILLOW_FEATURES), "", data
    )


def _cpus(env: Environment) -> Check:
    hw = env.hardware
    data = {"logical_cpus": hw.logical_cpus, "physical_cores": hw.physical_cores}
    if hw.physical_cores is None:
        return Check(
            "cpus",
            "CPUs",
            Status.warning,
            f"{hw.logical_cpus} logical, physical cores unknown",
            "threads fall back to one per logical CPU",
            data,
        )
    extra = hw.logical_cpus - hw.physical_cores
    message = f"{extra} hyperthreads" if extra else "no hyperthreads"
    return Check(
        "cpus",
        "CPUs",
        Status.ok,
        f"{hw.physical_cores} physical cores, {hw.logical_cpus} logical",
        message,
        data,
    )


def _cache(env: Environment) -> Check:
    size = env.hardware.cache_per_core
    if size is None:
        return Check(
            "cache",
            "Cache per core",
            Status.warning,
            "unknown",
            "blocks use the default size",
            {"bytes": None},
        )
    return Check(
        "cache",
        "Cache per core",
        Status.ok,
        _bytes(size),
        "largest data cache, shared out among its cores",
        {"bytes": size},
    )


def _threads(env: Environment) -> Check:
    hw = env.hardware
    threads = env.parallelism.threads
    data = {
        "threads": threads,
        "automatic": env.automatic.threads,
        "source": env.threads_source or "automatic",
    }
    value = f"{threads} per photo"
    if env.threads_source is not None:
        status = Status.ok
        message = f"set by {env.threads_source} (automatic: {env.automatic.threads})"
        if threads > hw.logical_cpus:
            status = Status.warning
            message += f"; more than the {hw.logical_cpus} CPUs this process may use"
        return Check("threads", "Threads", status, value, message, data)
    if hw.physical_cores is None:
        return Check(
            "threads",
            "Threads",
            Status.warning,
            value,
            "one per logical CPU (physical cores unknown; hyperthreads may slow it)",
            data,
        )
    message = "one per physical core"
    if hw.logical_cpus > hw.physical_cores:
        message += (
            f"; the {hw.logical_cpus} logical CPUs include hyperthreads, which share a "
            "core and don't speed up numpy"
        )
    return Check("threads", "Threads", Status.ok, value, message, data)


def _block(env: Environment) -> Check:
    block = env.parallelism.block_pixels
    data = {
        "block_pixels": block,
        "automatic": env.automatic.block_pixels,
        "source": env.block_source or "automatic",
    }
    value = _pixels(block)
    if env.block_source is not None:
        message = f"set by {env.block_source} (automatic: {_pixels(env.automatic.block_pixels)})"
        return Check("block_size", "Block size", Status.ok, value, message, data)
    size = env.hardware.cache_per_core
    if not size:
        return Check(
            "block_size",
            "Block size",
            Status.warning,
            value,
            "default (cache size unknown)",
            data,
        )
    message = (
        f"largest power of two that fits {_bytes(size)} at "
        f"{CACHE_BYTES_PER_BLOCK_PIXEL} bytes per pixel"
    )
    if block in (MIN_BLOCK_PIXELS, MAX_BLOCK_PIXELS):
        message += f", clamped to {_pixels(MIN_BLOCK_PIXELS)}-{_pixels(MAX_BLOCK_PIXELS)}"
    return Check("block_size", "Block size", Status.ok, value, message, data)


def _terminal(env: Environment) -> Check:
    graphics = env.terminal
    notes = [graphics.reason]
    if graphics.multiplexer:
        notes.append(f"inside {graphics.multiplexer}, images may need passthrough enabled")
    if not graphics.tty:
        notes.append("output isn't a terminal now")
    notes.append("a guess from environment variables")
    status = Status.ok if graphics.protocol else Status.warning
    if graphics.protocol is None:
        notes.append("terminal previews will need --png instead")
    data = {
        "protocol": graphics.protocol,
        "certain": graphics.certain,
        "terminal": graphics.terminal,
        "multiplexer": graphics.multiplexer,
        "tty": graphics.tty,
    }
    return Check(
        "terminal_graphics", "Terminal graphics", status, graphics.summary, "; ".join(notes), data
    )


def build_checks(env: Environment) -> list[Check]:
    """Every check, in display order. Pure: no IO."""
    return [
        Check("picturesq", "picturesq", Status.ok, env.picturesq),
        _python(env),
        Check("platform", "Platform", Status.ok, env.platform, env.platform_release),
        _libraw(env),
        _libraw_features(env),
        *(_library(name, env.libraries.get(name)) for name in LIBRARIES),
        _pillow_features(env),
        _cpus(env),
        _cache(env),
        _threads(env),
        _block(env),
        _terminal(env),
    ]


# Rendering ---------------------------------------------------------------------------------


def summary(checks: list[Check]) -> dict[str, int]:
    return {status.value: sum(1 for c in checks if c.status is status) for status in Status}


def render_text(checks: list[Check]) -> str:
    """A compact aligned table: status, check, value, message."""
    widths = [max(len(getattr(c, attr)) for c in checks) for attr in ("status", "label", "value")]
    lines = []
    for c in checks:
        cells = (c.status.value, c.label, c.value)
        row = "  ".join(cell.ljust(width) for cell, width in zip(cells, widths, strict=True))
        lines.append(f"{row}  {c.message}".rstrip())
    counts = summary(checks)
    lines.append(f"{counts['error']} error(s), {counts['warning']} warning(s)")
    return "\n".join(lines)


def render_json(checks: list[Check]) -> str:
    document = {
        "checks": [
            {
                "check": c.check,
                "status": c.status.value,
                "value": c.value,
                "message": c.message,
                "data": dict(c.data),
            }
            for c in checks
        ],
        "summary": summary(checks),
    }
    return json.dumps(document, indent=2)


# IO at the edges ---------------------------------------------------------------------------


def _distribution_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


class _RootContext(Protocol):
    """The parts of click's context we read (typer vendors click privately)."""

    @property
    def command(self) -> Any: ...

    def get_parameter_source(self, name: str) -> Enum | None: ...


def _override_source(ctx: _RootContext, name: str) -> str | None:
    """The root option or env variable that set ``name``, or None if it's the default."""
    source = ctx.get_parameter_source(name)
    option = next((p for p in ctx.command.params if p.name == name), None)
    if option is None or source is None:
        return None
    # Compared by name: typer vendors click privately, so its enum isn't importable.
    if source.name == "COMMANDLINE":
        return option.opts[0]
    if source.name == "ENVIRONMENT":
        envvar = option.envvar
        return envvar if isinstance(envvar, str) else "environment"
    return None


def gather(ctx: typer.Context) -> Environment:
    """Read the real environment. ``ctx`` is the command's context (for the root options)."""
    import rawpy._rawpy as libraw
    from PIL import features

    root = ctx.find_root()
    hardware = detect()
    flags = getattr(libraw, "flags", None)
    return Environment(
        picturesq=__version__,
        python=(sys.version_info.major, sys.version_info.minor, sys.version_info.micro),
        platform=f"{platform.system()} {platform.machine()}",
        platform_release=platform.release(),
        libraw=tuple(libraw.libraw_version),
        libraw_flags=dict(flags) if isinstance(flags, dict) else None,
        libraries={name: _distribution_version(name) for name in LIBRARIES},
        pillow_features={name: bool(features.check(name)) for name in PILLOW_FEATURES},
        hardware=hardware,
        parallelism=parallel.current(),
        automatic=parallel.auto(hardware=hardware),
        threads_source=_override_source(root, "threads"),
        block_source=_override_source(root, "block_pixels"),
        terminal=detect_terminal_graphics(os.environ, tty=sys.stdout.isatty()),
    )


def run_doctor(ctx: typer.Context, *, as_json: bool) -> None:
    """Body of `picturesq doctor`. Exits 1 if any check is an error."""
    checks = build_checks(gather(ctx))
    if as_json:
        sys.stdout.write(render_json(checks) + "\n")
    else:
        typer.echo(render_text(checks))
    if any(c.status is Status.error for c in checks):
        raise typer.Exit(code=EXIT_ERROR)
