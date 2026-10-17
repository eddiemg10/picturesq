"""Worker sizing (a pure function) and the worker pool's ordering and error handling."""

import os
import time
from collections.abc import Sequence
from pathlib import Path

import pytest

from picturesq.config import ProjectConfig
from picturesq.pipeline.budget import PROCESS_OVERHEAD_BYTES
from picturesq.pipeline.export import PhotoResult, _export_in_workers
from picturesq.pipeline.workers import (
    DEFAULT_MEMORY_FRACTION,
    Start,
    WorkerPlan,
    default_memory_budget,
    parse_memory_budget,
    photo_bytes,
    photos_to_start,
    plan_workers,
)

GIB = 2**30
POCKET_4 = 7680 * 4320  # 33 MP


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3GB", 3 * 10**9),
        ("2.5GiB", int(2.5 * GIB)),
        ("800MB", 800 * 10**6),
        ("1500 MiB", 1500 * 2**20),
        ("4g", 4 * 10**9),
        ("123456", 123456),
    ],
)
def test_parse_memory_budget(text: str, expected: int) -> None:
    assert parse_memory_budget(text) == expected


@pytest.mark.parametrize("text", ["", "lots", "3 parsecs", "-1GB", "0", "GB"])
def test_parse_memory_budget_rejects_nonsense(text: str) -> None:
    with pytest.raises(ValueError):
        parse_memory_budget(text)


def test_default_budget_is_a_share_of_available_memory() -> None:
    assert default_memory_budget(10 * GIB) == int(10 * GIB * DEFAULT_MEMORY_FRACTION)
    assert default_memory_budget(None) is None


LARGE, SMALL = POCKET_4, 4032 * 3024  # 33 MP and 12 MP
OVERHEAD = PROCESS_OVERHEAD_BYTES


def _budget(*photos: int) -> int:
    """Exactly enough for these photos at once, one worker each."""
    return sum(OVERHEAD + photo_bytes(pixels) for pixels in photos)


def _run(plan: WorkerPlan) -> list[list[Start]]:
    """Simulate a batch: start what may start, then finish the oldest running photo."""
    pending, running, rounds = plan.order(), [], []
    while pending or running:
        starts = photos_to_start(plan, pending, running)
        rounds.append(starts)
        for start in starts:
            pending.remove(start.index)
            running.append(start.index)
        assert running, "nothing could start"
        running.pop(0)
    return rounds


def test_largest_photos_start_first_in_a_stable_order() -> None:
    plan = plan_workers([SMALL, LARGE, SMALL, LARGE], cores=4, memory_budget=None)
    assert plan.order() == [1, 3, 0, 2]


def test_workers_are_as_many_as_the_smallest_photos_fit() -> None:
    plan = plan_workers([LARGE, SMALL, SMALL], cores=4, memory_budget=_budget(SMALL, SMALL))
    assert plan.workers == 2
    plan = plan_workers([LARGE] * 6, cores=4, memory_budget=_budget(LARGE, LARGE))
    assert plan.workers == 2
    assert plan_workers([LARGE] * 6, cores=4, memory_budget=_budget(LARGE)).workers == 1


def test_photos_at_once_are_capped_by_cores_and_workers_option() -> None:
    lots = 100 * GIB
    assert plan_workers([SMALL] * 9, cores=4, memory_budget=lots).max_photos == 2
    assert plan_workers([SMALL] * 9, cores=4, memory_budget=lots).workers == 2
    assert plan_workers([SMALL] * 9, cores=8, memory_budget=lots).workers == 4
    assert plan_workers([SMALL] * 9, cores=4, memory_budget=lots, max_photos=4).workers == 4
    assert plan_workers([SMALL] * 9, cores=4, memory_budget=lots, threads=1).workers == 4
    assert plan_workers([SMALL] * 9, cores=4, memory_budget=lots, threads=4).workers == 1
    assert plan_workers([SMALL] * 2, cores=16, memory_budget=lots).workers == 2


def test_large_photos_one_at_a_time_then_small_ones_in_pairs() -> None:
    """The example from #22: 6 large + 4 small photos, room for one large photo at a time."""
    pixels = [SMALL, LARGE] * 2 + [LARGE] * 4 + [SMALL] * 2
    budget = 2 * OVERHEAD + photo_bytes(LARGE)  # two workers, one large photo
    plan = plan_workers(pixels, cores=4, memory_budget=budget)
    assert plan.workers == 2
    rounds = [round_ for round_ in _run(plan) if round_]
    started = [[(pixels[start.index], start.threads) for start in round_] for round_ in rounds]
    assert started[:6] == [[(LARGE, 4)]] * 6
    assert started[6] == [(SMALL, 2), (SMALL, 2)]
    assert all(threads == 2 for round_ in started[7:] for _, threads in round_)


def test_a_photo_waits_until_its_peak_fits() -> None:
    plan = plan_workers([LARGE, SMALL, SMALL], cores=4, memory_budget=_budget(SMALL, SMALL))
    assert plan.workers == 2
    # The large photo beside two idle workers is over this budget: it starts anyway, alone.
    assert plan.over_budget
    assert photos_to_start(plan, [0, 1, 2], []) == [Start(index=0, threads=4)]
    assert photos_to_start(plan, [1, 2], [0]) == []
    assert photos_to_start(plan, [1, 2], []) == [Start(1, 2), Start(2, 2)]


def test_photos_start_strictly_in_order() -> None:
    """A small photo doesn't overtake a waiting large one (it would delay it again)."""
    pixels = [LARGE, LARGE, SMALL]
    plan = plan_workers(pixels, cores=4, memory_budget=_budget(LARGE, SMALL))
    assert plan.workers == 2
    assert photos_to_start(plan, [1, 2], [0]) == []


def test_threads_split_the_cores_between_running_photos() -> None:
    plan = plan_workers([SMALL] * 6, cores=4, memory_budget=100 * GIB)
    assert photos_to_start(plan, [0, 1, 2], []) == [Start(0, 2), Start(1, 2)]
    assert photos_to_start(plan, [2, 3], [0]) == [Start(2, 2)]
    fixed = plan_workers([SMALL] * 6, cores=4, memory_budget=100 * GIB, threads=1)
    assert [start.threads for start in photos_to_start(fixed, [0, 1, 2], [])] == [1, 1, 1]


def test_unknown_budget_runs_one_photo_at_a_time() -> None:
    plan = plan_workers([SMALL] * 3, cores=4, memory_budget=None)
    assert plan.workers == 1
    assert not plan.over_budget
    assert photos_to_start(plan, [0, 1, 2], []) == [Start(0, 4)]


def test_no_photos_or_cores_still_plans_one_worker() -> None:
    plan = plan_workers([], cores=0, memory_budget=None)
    assert (plan.workers, plan.max_photos) == (1, 1)


# Worker processes import these by name, so they live at module level.


def _slow_first(
    original: Path, _config: ProjectConfig, exports_dir: Path, names: Sequence[str]
) -> PhotoResult:
    time.sleep(1.5 if original.name == "a.dng" else 0.0)
    result = PhotoResult(name=original.name, outputs={n: exports_dir / n for n in names})
    if original.name == "b.dng":
        result.error = "cannot decode b.dng: corrupt"
    return result


def _dies_on_b(
    original: Path, _config: ProjectConfig, exports_dir: Path, names: Sequence[str]
) -> PhotoResult:
    if original.name == "b.dng":
        os._exit(1)  # as if the operating system killed the worker
    time.sleep(0.5)
    return PhotoResult(name=original.name)


def test_pool_keeps_photo_order_and_reports_as_photos_finish(tmp_path: Path) -> None:
    originals = [tmp_path / name for name in ("a.dng", "b.dng", "c.dng")]
    finished: list[str] = []
    plan = plan_workers([3, 2, 1], cores=4, memory_budget=100 * GIB)  # starts a.dng first
    results = _export_in_workers(
        originals,
        ProjectConfig(),
        tmp_path,
        ["web"],
        lambda photo: finished.append(photo.name),
        plan,
        export=_slow_first,
    )
    assert [photo.name for photo in results] == ["a.dng", "b.dng", "c.dng"]
    assert finished[-1] == "a.dng"  # the slow one, reported last
    assert sorted(finished) == ["a.dng", "b.dng", "c.dng"]
    assert results[1].error is not None and "corrupt" in results[1].error
    assert results[0].outputs == {"web": tmp_path / "web"}


def test_a_dead_worker_fails_its_photos_instead_of_the_run(tmp_path: Path) -> None:
    originals = [tmp_path / name for name in ("a.dng", "b.dng", "c.dng", "d.dng")]
    plan = plan_workers([1] * 4, cores=4, memory_budget=100 * GIB)
    results = _export_in_workers(
        originals, ProjectConfig(), tmp_path, ["web"], None, plan, export=_dies_on_b
    )
    assert all(photo.error for photo in results[1:])
    assert [photo.name for photo in results] == ["a.dng", "b.dng", "c.dng", "d.dng"]
    assert results[1].error is not None and "stopped unexpectedly" in results[1].error
