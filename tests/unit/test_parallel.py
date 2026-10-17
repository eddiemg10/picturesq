import threading

import numpy as np
import pytest

from picturesq import parallel
from picturesq.config import ProjectConfig
from picturesq.hardware import Hardware
from picturesq.pipeline.export import render_output, render_scene


def test_run_runs_every_task_on_several_threads() -> None:
    seen: list[int] = []
    names: set[str] = set()
    lock = threading.Lock()

    def task(number: int) -> None:
        with lock:
            seen.append(number)
            names.add(threading.current_thread().name)

    with parallel.using(parallel.Parallelism(threads=3, block_pixels=1024)):
        parallel.run(lambda n=n: task(n) for n in range(50))
    assert sorted(seen) == list(range(50))
    assert all(name.startswith("picturesq") for name in names)


def test_run_reraises_after_all_tasks_finish() -> None:
    done: list[int] = []

    def task(number: int) -> None:
        if number == 3:
            raise ValueError("boom")
        done.append(number)

    with (
        parallel.using(parallel.Parallelism(threads=2, block_pixels=1024)),
        pytest.raises(ValueError, match="boom"),
    ):
        parallel.run(lambda n=n: task(n) for n in range(10))
    assert sorted(done) == [n for n in range(10) if n != 3]


def test_nested_run_is_serial_instead_of_deadlocking() -> None:
    results: list[int] = []
    lock = threading.Lock()

    def outer(number: int) -> None:
        def inner() -> None:
            with lock:
                results.append(number)

        parallel.run([inner, inner])

    with parallel.using(parallel.Parallelism(threads=2, block_pixels=1024)):
        parallel.run(lambda n=n: outer(n) for n in range(4))
    assert sorted(results) == [0, 0, 1, 1, 2, 2, 3, 3]


def test_blocks_cover_everything_once() -> None:
    with parallel.using(parallel.Parallelism(threads=1, block_pixels=1000)):
        slices = parallel.pixel_blocks(2500)
        rows = parallel.row_blocks(height=25, width=300)
        tall = parallel.row_blocks(height=25, width=300, min_rows=10)
    assert [(s.start, s.stop) for s in slices] == [(0, 1000), (1000, 2000), (2000, 2500)]
    assert rows[0] == (0, 3) and rows[-1] == (24, 25)
    assert tall == [(0, 10), (10, 20), (20, 25)]


def test_auto_uses_physical_cores_and_cache() -> None:
    laptop = Hardware(logical_cpus=8, physical_cores=4, cache_per_core=1536 * 1024)
    assert parallel.auto(hardware=laptop) == parallel.Parallelism(threads=4, block_pixels=65536)
    unknown = Hardware(logical_cpus=2, physical_cores=None, cache_per_core=None)
    assert parallel.auto(hardware=unknown) == parallel.Parallelism(
        threads=2, block_pixels=parallel.DEFAULT_BLOCK_PIXELS
    )
    assert parallel.auto(threads=3, block_pixels=5000, hardware=laptop) == parallel.Parallelism(
        threads=3, block_pixels=5000
    )


def test_block_size_is_clamped() -> None:
    assert parallel.block_pixels_for_cache(64 * 1024) == parallel.MIN_BLOCK_PIXELS
    assert parallel.block_pixels_for_cache(1024**3) == parallel.MAX_BLOCK_PIXELS


@pytest.mark.parametrize(
    ("threads", "block_pixels"), [(1, 1000), (3, 1000), (4, 3001), (2, 1 << 18)]
)
def test_output_is_identical_for_any_threads_and_block_size(
    threads: int, block_pixels: int
) -> None:
    """Same originals + config + version = same output, on every machine."""
    rng = np.random.default_rng(5)
    image = (rng.random((157, 233, 3), dtype=np.float32) ** 3 * 6.0).astype(np.float32)
    config = ProjectConfig()
    outputs = {
        "web": config.export.outputs["web"].model_copy(update={"long_edge": 120}),
        "archive": config.export.outputs["archive"],
    }

    def render() -> list[np.ndarray]:
        scene = render_scene(image.copy(), config)
        display = config.grade.display_transform
        return [scene] + [render_output(scene, spec, display) for spec in outputs.values()]

    with parallel.using(parallel.Parallelism(threads=1, block_pixels=1 << 16)):
        expected = render()
    with parallel.using(parallel.Parallelism(threads=threads, block_pixels=block_pixels)):
        actual = render()
    for want, got in zip(expected, actual, strict=True):
        np.testing.assert_array_equal(got, want)
