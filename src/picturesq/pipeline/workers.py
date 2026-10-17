"""Which photos to export at once, and with how many threads each.

A **worker** is a separate process that exports one photo at a time. Several workers
export photos in parallel, within a **memory budget**: each photo is predicted to need its
own photo peak (``picturesq.pipeline.budget``, from its pixel count, read from the
original's header before anything is decoded), and a photo starts only when its peak fits
beside the photos already running. The largest photos go first, so a big photo never runs
alone at the end while the others wait. Each photo's threads are chosen when it starts:
the physical cores divided by the photos running then. A run of six 33 MP and four 12 MP
photos on a 4-core laptop with room for one 33 MP photo at a time exports the large ones
one by one on 4 threads, then the small ones two at a time on 2 threads each.

Memory is counted per process, not per photo: a photo peak is a fixed part (the
interpreter and libraries, which a live worker holds even while idle) plus a part per
pixel. So the budget pays one fixed part for every worker process and one per-pixel part
for every running photo.

At most ``cores // MIN_THREADS_PER_PHOTO`` photos run at once by default, measured on a
4-core laptop (ADR-0015): 2 photos x 2 threads beat 1 x 4 by 5-17 %, and 4 x 1 was no
faster than 2 x 2 but used ~50 % more memory.

Like threads, these are machine settings (CLI options and environment variables), never
project config: a photo's pixels and sidecar are identical whichever worker exports it and
with how many threads. The decisions are pure functions of the photos' sizes, the photos
running, the budget and the cores, unit-tested without a machine to match.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from picturesq.pipeline.budget import PEAK_BYTES_PER_PIXEL, PROCESS_OVERHEAD_BYTES

DEFAULT_MEMORY_FRACTION: Final = 0.6
"""Default memory budget: this share of the memory available when the run starts.

The rest is left for the parent process, the operating system's file cache and whatever
else is running; available memory can also shrink while we run.
"""
MIN_THREADS_PER_PHOTO: Final = 2
"""Photos running at once are capped so each gets at least this many threads (measured)."""

_UNITS: Final = {
    "": 1,
    "b": 1,
    "k": 10**3,
    "kb": 10**3,
    "kib": 2**10,
    "m": 10**6,
    "mb": 10**6,
    "mib": 2**20,
    "g": 10**9,
    "gb": 10**9,
    "gib": 2**30,
    "t": 10**12,
    "tb": 10**12,
    "tib": 2**40,
}
_BUDGET = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]*)\s*$")


def parse_memory_budget(text: str) -> int:
    """``"3GB"`` (10**9), ``"2.5GiB"`` (2**30), ``"800MB"`` or a plain number of bytes.

    Raises ValueError for anything else, or a budget that isn't positive.
    """
    match = _BUDGET.match(text)
    unit = match.group(2).lower() if match else None
    if match is None or unit not in _UNITS:
        raise ValueError(f"not a memory size: {text!r} (examples: 3GB, 2.5GiB, 800MB)")
    value = int(float(match.group(1)) * _UNITS[unit])
    if value <= 0:
        raise ValueError(f"the memory budget must be positive, not {text!r}")
    return value


def default_memory_budget(available: int | None) -> int | None:
    """The budget when none is given: a share of ``available`` memory (None: unknown)."""
    if available is None:
        return None
    return int(available * DEFAULT_MEMORY_FRACTION)


def format_bytes(count: int) -> str:
    return f"{count / 2**30:.1f} GiB"


def photo_bytes(pixels: int) -> int:
    """The part of a photo peak that the photo itself adds to a live worker."""
    return PEAK_BYTES_PER_PIXEL * pixels


@dataclass(frozen=True)
class WorkerPlan:
    """How a batch of photos runs; built by :func:`plan_workers`."""

    pixels: tuple[int, ...]
    """Pixels of each photo, in the originals' order (0 when unreadable)."""
    workers: int
    """Worker processes: the most photos that can ever run at once."""
    max_photos: int
    """Photos running at once never exceed this (``--workers``, or the cores)."""
    cores: int
    memory_budget: int | None
    """Bytes all workers together may use; None when unknown (one photo at a time)."""
    threads: int | None = None
    """Threads for every photo (``--threads``); None: chosen as each photo starts."""

    @property
    def over_budget(self) -> bool:
        """The largest photo alone (beside idle workers) needs more than the budget; it
        runs anyway, by itself."""
        if self.memory_budget is None:
            return False
        largest = max(self.pixels, default=0)
        return self.idle_bytes + photo_bytes(largest) > self.memory_budget

    @property
    def idle_bytes(self) -> int:
        """What the worker processes hold before any photo: one fixed part each."""
        return self.workers * PROCESS_OVERHEAD_BYTES

    def order(self) -> list[int]:
        """Indices of the photos in the order they start: largest first."""
        return sorted(range(len(self.pixels)), key=lambda index: -self.pixels[index])

    def describe(self) -> str:
        budget = "unknown" if self.memory_budget is None else format_bytes(self.memory_budget)
        workers = "1 worker" if self.workers == 1 else f"{self.workers} workers"
        return f"{workers}, memory budget {budget}"


def plan_workers(
    pixels: Sequence[int],
    *,
    cores: int,
    memory_budget: int | None,
    max_photos: int | None = None,
    threads: int | None = None,
) -> WorkerPlan:
    """Plan a batch of photos of ``pixels`` pixels each.

    ``max_photos`` (``--workers``) caps the photos running at once; by default the cores
    do: one photo per ``threads`` cores when threads are given, else one per
    ``MIN_THREADS_PER_PHOTO`` cores. The workers are as many as the budget lets run at
    once (each worker's fixed part plus the smallest photos), within that cap; at least one.
    """
    cores = max(1, cores)
    if max_photos is None:
        max_photos = cores // (threads or MIN_THREADS_PER_PHOTO)
    max_photos = max(1, max_photos)
    workers = 0
    if memory_budget is not None:
        used = 0
        for size in sorted(pixels)[:max_photos]:
            used += PROCESS_OVERHEAD_BYTES + photo_bytes(size)
            if used > memory_budget:
                break
            workers += 1
    return WorkerPlan(
        pixels=tuple(pixels),
        workers=max(1, workers),
        max_photos=max_photos,
        cores=cores,
        memory_budget=memory_budget,
        threads=threads,
    )


@dataclass(frozen=True)
class Start:
    """Start photo ``index`` now, on ``threads`` threads."""

    index: int
    threads: int


def photos_to_start(
    plan: WorkerPlan, pending: Sequence[int], running: Sequence[int]
) -> list[Start]:
    """Which of the ``pending`` photos (indices, in starting order) start now, beside the
    ``running`` ones, and with how many threads.

    Strictly in order: a photo that doesn't fit waits, and so does everything after it
    (otherwise small photos would keep overtaking a large one). With nothing running, the
    next photo starts even when it alone exceeds the budget. The cores are split between
    all the photos running once these start.
    """
    room = min(plan.max_photos, plan.workers) - len(running)
    budget = plan.memory_budget
    used = plan.idle_bytes
    used += sum(photo_bytes(plan.pixels[index]) for index in running)
    chosen: list[int] = []
    for index in pending:
        if len(chosen) >= room:
            break
        need = photo_bytes(plan.pixels[index])
        if (running or chosen) and (budget is None or used + need > budget):
            break
        used += need
        chosen.append(index)
    threads = plan.threads or max(1, plan.cores // max(1, len(running) + len(chosen)))
    return [Start(index=index, threads=threads) for index in chosen]
