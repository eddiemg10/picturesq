"""Run independent blocks of one image on several cores.

numpy releases Python's GIL inside each operation, so threads working on different blocks of
an image compute at the same time while sharing the image (no extra copies, unlike one
process per photo). Two settings matter, and both are chosen from the hardware by default:

- **threads**: one per physical core (``picturesq.hardware``). A hyperthread shares its
  core's arithmetic units and cache, so it adds nothing to numpy's tight loops.
- **block size**: small enough that a block's temporaries stay in its core's cache, so the
  cores don't queue for the one connection to main memory; large enough that the Python
  overhead of each numpy call (which holds the GIL) stays small. Measured in #68: 64k-128k
  pixels was ~3.5x faster on 4 threads than 256k, and 16k was slower than one thread.

Blocks never overlap in what they write, and each block's maths doesn't depend on where the
block boundaries fall, so the result is bit-identical for any threads and block size
(tested). That is what makes choosing them per machine safe: same originals + config +
version = same output.

The settings are process-wide, set by the CLI (``--threads``, ``--block-pixels``) with
``use()``. Image operations only read them; library callers that never call ``use()`` run
on one thread with the default block size.
"""

from __future__ import annotations

import ctypes
import sys
import threading
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cache
from typing import Final

from picturesq.hardware import Hardware, detect

DEFAULT_BLOCK_PIXELS: Final = 1 << 16
"""Block size when the cache size is unknown (and for library callers)."""
MIN_BLOCK_PIXELS: Final = 1 << 15
MAX_BLOCK_PIXELS: Final = 1 << 18
CACHE_BYTES_PER_BLOCK_PIXEL: Final = 24
"""Cache a block needs per pixel: its float32 RGB input and one same-sized temporary.

A heuristic fitted to one machine (i5-8250U: 1.5 MB of L3 per core, best at 64k pixels);
the speed plateau is wide (32k-128k within ~20 %), so a rough figure is enough.
"""


_M_ARENA_MAX: Final = -8
"""glibc's ``mallopt`` parameter for the maximum number of arenas (``malloc.h``)."""


@dataclass(frozen=True)
class Parallelism:
    threads: int
    block_pixels: int


_current = Parallelism(threads=1, block_pixels=DEFAULT_BLOCK_PIXELS)
_pools: dict[int, ThreadPoolExecutor] = {}
_pools_lock = threading.Lock()
_inside = threading.local()


def auto(
    threads: int | None = None, block_pixels: int | None = None, hardware: Hardware | None = None
) -> Parallelism:
    """Settings for this machine; an explicit ``threads`` or ``block_pixels`` wins."""
    hardware = hardware or detect()
    if threads is None:
        threads = hardware.physical_cores or hardware.logical_cpus
    if block_pixels is None:
        block_pixels = block_pixels_for_cache(hardware.cache_per_core)
    return Parallelism(threads=max(1, threads), block_pixels=max(1, block_pixels))


def block_pixels_for_cache(cache_per_core: int | None) -> int:
    """The largest power of two whose block fits ``cache_per_core``, clamped."""
    if not cache_per_core:
        return DEFAULT_BLOCK_PIXELS
    fits = max(1, cache_per_core // CACHE_BYTES_PER_BLOCK_PIXEL)
    return min(MAX_BLOCK_PIXELS, max(MIN_BLOCK_PIXELS, 1 << (fits.bit_length() - 1)))


def current() -> Parallelism:
    return _current


def use(settings: Parallelism) -> None:
    """Make ``settings`` the process-wide parallelism."""
    global _current
    if settings.threads > 1:
        limit_allocator_arenas()
    _current = settings


@cache
def limit_allocator_arenas() -> bool:
    """On glibc (Linux), make every thread allocate from one shared memory pool (arena).

    glibc gives each new thread its own arena, and an arena keeps freed blocks for reuse
    instead of returning them to the operating system. Our block temporaries (~1 MB each)
    then pile up per thread: measured on a 33 MP export with 4 threads, the peak rose from
    0.93 to 1.45 GiB. One arena brings it back, at no measured speed cost (numpy allocates
    rarely compared with the work it does per block). Call before the threads start;
    returns whether the limit was set (False on other C libraries, which don't need it).
    """
    if not sys.platform.startswith("linux"):
        return False
    try:
        libc = ctypes.CDLL(None)
        return bool(libc.mallopt(_M_ARENA_MAX, 1))
    except (OSError, AttributeError):  # not glibc (e.g. musl), or no mallopt
        return False


@contextmanager
def using(settings: Parallelism) -> Iterator[None]:
    """``use(settings)`` for the duration of a ``with`` block (tests, scripts)."""
    previous = _current
    use(settings)
    try:
        yield
    finally:
        use(previous)


def pixel_blocks(count: int) -> list[slice]:
    """Slices covering ``range(count)`` in blocks of the current block size."""
    size = _current.block_pixels
    return [slice(start, min(count, start + size)) for start in range(0, count, size)]


def row_blocks(height: int, width: int, min_rows: int = 1) -> list[tuple[int, int]]:
    """``(top, bottom)`` row ranges of about the current block size each, at least
    ``min_rows`` tall (for neighbourhood operations, whose blocks overlap by a radius)."""
    rows = max(1, min_rows, _current.block_pixels // max(1, width))
    return [(top, min(height, top + rows)) for top in range(0, height, rows)]


def run(tasks: Iterable[Callable[[], object]]) -> None:
    """Run ``tasks`` on the current number of threads and wait for all of them.

    Tasks must not write to the same memory. A task that calls ``run`` itself runs its own
    tasks serially (a pool waiting on itself would deadlock). The first exception is
    re-raised after every task has finished.
    """
    tasks = list(tasks)
    if _current.threads <= 1 or len(tasks) <= 1 or getattr(_inside, "active", False):
        for task in tasks:
            task()
        return
    futures = [_pool(_current.threads).submit(_inside_pool, task) for task in tasks]
    errors = [future.exception() for future in futures]
    for error in errors:
        if error is not None:
            raise error


def _inside_pool(task: Callable[[], object]) -> None:
    _inside.active = True
    try:
        task()
    finally:
        _inside.active = False


def _pool(threads: int) -> ThreadPoolExecutor:
    with _pools_lock:
        pool = _pools.get(threads)
        if pool is None:
            pool = _pools[threads] = ThreadPoolExecutor(threads, thread_name_prefix="picturesq")
        return pool
