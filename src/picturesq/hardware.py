"""What the machine offers: physical cores and the cache each core can count on.

Used to choose threads and block sizes automatically (``picturesq.parallel``), so nobody has
to tune them per machine. Read from the operating system without extra dependencies:
Linux ``/sys``, macOS ``sysctl``, Windows ``GetLogicalProcessorInformation``. Every reader
returns None when it can't tell, and callers fall back to safe defaults.

Physical cores, not logical CPUs: a hyperthread shares its core's arithmetic units and
cache with its sibling, which gains nothing on numpy's tight loops (measured in #68: 8
threads were slower than 4 on a 4-core, 8-thread laptop).
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
from dataclasses import dataclass
from functools import cache
from pathlib import Path

_SYS_CPU = Path("/sys/devices/system/cpu")
_CGROUP_CPU_MAX = Path("/sys/fs/cgroup/cpu.max")


@dataclass(frozen=True)
class Hardware:
    """What was detected; None means unknown."""

    logical_cpus: int
    """CPUs this process may run on (affinity and container quota applied)."""
    physical_cores: int | None
    cache_per_core: int | None
    """Bytes of the largest data cache divided among the physical cores sharing it."""


@cache
def detect() -> Hardware:
    """Detect once per process; the answer doesn't change while we run."""
    logical = _usable_cpus()
    if sys.platform.startswith("linux"):
        physical, cache_per_core = _linux()
    elif sys.platform == "darwin":
        physical, cache_per_core = _macos()
    elif sys.platform == "win32":
        physical, cache_per_core = _windows()
    else:
        physical, cache_per_core = None, None
    if physical is not None:
        physical = max(1, min(physical, logical))
    return Hardware(logical_cpus=logical, physical_cores=physical, cache_per_core=cache_per_core)


def _usable_cpus() -> int:
    if hasattr(os, "sched_getaffinity"):
        count = len(os.sched_getaffinity(0))
    else:
        count = os.cpu_count() or 1
    quota = _cgroup_quota()
    return max(1, min(count, quota) if quota is not None else count)


def _cgroup_quota() -> int | None:
    """CPUs a container may use (cgroup v2 ``cpu.max``), or None when unlimited."""
    try:
        quota, period = _CGROUP_CPU_MAX.read_text().split()
    except (OSError, ValueError):
        return None
    if quota == "max":
        return None
    return max(1, math.ceil(int(quota) / int(period)))


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def parse_cpu_list(text: str) -> set[int]:
    """``"0-3,8,10-11"`` → ``{0, 1, 2, 3, 8, 10, 11}`` (the kernel's CPU list format)."""
    cpus: set[int] = set()
    for part in text.split(","):
        if not part:
            continue
        first, _, last = part.partition("-")
        cpus.update(range(int(first), int(last or first) + 1))
    return cpus


def parse_size(text: str) -> int:
    """A sysfs cache size, ``"6144K"`` or ``"1M"``, in bytes."""
    units = {"K": 1 << 10, "M": 1 << 20, "G": 1 << 30}
    if text[-1:].upper() in units:
        return int(text[:-1]) * units[text[-1].upper()]
    return int(text)


def _linux(root: Path = _SYS_CPU, allowed: set[int] | None = None) -> tuple[int | None, int | None]:
    """``(physical cores, cache per core)`` from sysfs, over the CPUs in ``allowed``
    (default: this process's affinity)."""
    if allowed is None and hasattr(os, "sched_getaffinity"):
        allowed = os.sched_getaffinity(0)
    core_of: dict[int, tuple[str, str]] = {}
    for cpu in root.glob("cpu[0-9]*"):
        number = int(cpu.name[3:])
        if allowed is not None and number not in allowed:
            continue
        package = _read(cpu / "topology" / "physical_package_id")
        core = _read(cpu / "topology" / "core_id")
        if package is None or core is None:
            continue
        core_of[number] = (package, core)
    physical = len(set(core_of.values())) or None
    return physical, _linux_cache_per_core(root, core_of)


def _linux_cache_per_core(root: Path, core_of: dict[int, tuple[str, str]]) -> int | None:
    if not core_of:
        return None
    first = min(core_of)
    best: tuple[int, int, set[int]] | None = None  # (level, size, cpus sharing it)
    for index in (root / f"cpu{first}" / "cache").glob("index[0-9]*"):
        level, kind = _read(index / "level"), _read(index / "type")
        size, shared = _read(index / "size"), _read(index / "shared_cpu_list")
        if None in (level, kind, size, shared) or kind == "Instruction":
            continue
        assert level is not None and size is not None and shared is not None
        entry = (int(level), parse_size(size), parse_cpu_list(shared))
        if best is None or entry[0] > best[0]:
            best = entry
    if best is None:
        return None
    sharing = {core_of[cpu] for cpu in best[2] if cpu in core_of}
    return best[1] // max(1, len(sharing))


def _sysctl(name: str) -> int | None:
    try:
        result = subprocess.run(
            ["sysctl", "-n", name], capture_output=True, text=True, check=False, timeout=2
        )
        return int(result.stdout.strip()) if result.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _macos() -> tuple[int | None, int | None]:
    physical = _sysctl("hw.physicalcpu")
    # Apple silicon: the performance cores' L2 is the last cache the CPU owns; Intel Macs
    # report an L3 shared by every core.
    l2, per_l2 = _sysctl("hw.perflevel0.l2cachesize"), _sysctl("hw.perflevel0.cpusperl2")
    if l2 is not None and per_l2:
        return physical, l2 // per_l2
    l3 = _sysctl("hw.l3cachesize")
    if l3 is not None and physical:
        return physical, l3 // physical
    return physical, None


def _windows() -> tuple[int | None, int | None]:
    import ctypes
    from ctypes import wintypes

    class CacheDescriptor(ctypes.Structure):
        _fields_ = (
            ("level", ctypes.c_ubyte),
            ("associativity", ctypes.c_ubyte),
            ("line_size", ctypes.c_ushort),
            ("size", wintypes.DWORD),
            ("type", ctypes.c_int),
        )

    class Detail(ctypes.Union):
        _fields_ = (
            ("flags", ctypes.c_ubyte),
            ("node", wintypes.DWORD),
            ("cache", CacheDescriptor),
            ("reserved", ctypes.c_ulonglong * 2),
        )

    class ProcessorInformation(ctypes.Structure):
        _fields_ = (
            ("mask", ctypes.c_size_t),
            ("relationship", ctypes.c_int),
            ("detail", Detail),
        )

    relation_core, relation_cache = 0, 2
    cache_unified, cache_data = 0, 2
    try:
        get = ctypes.windll.kernel32.GetLogicalProcessorInformation  # type: ignore[attr-defined]
        length = wintypes.DWORD(0)
        get(None, ctypes.byref(length))
        count = length.value // ctypes.sizeof(ProcessorInformation)
        records = (ProcessorInformation * count)()
        if not count or not get(records, ctypes.byref(length)):
            return None, None
    except (AttributeError, OSError):
        return None, None
    cores = [r for r in records if r.relationship == relation_core]
    physical = len(cores) or None
    logical_per_core = max(1, sum(bin(r.mask).count("1") for r in cores) // max(1, len(cores)))
    best: tuple[int, int, int] | None = None  # (level, size, logical CPUs sharing it)
    for record in records:
        if record.relationship != relation_cache:
            continue
        descriptor = record.detail.cache
        if descriptor.type not in (cache_unified, cache_data):
            continue
        entry = (descriptor.level, descriptor.size, bin(record.mask).count("1"))
        if best is None or entry[0] > best[0]:
            best = entry
    if best is None:
        return physical, None
    return physical, best[1] // max(1, best[2] // logical_per_core)
