import json
import time

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from picturesq.normalise import PhotoStats, median_ev, photo_stats
from picturesq.normalise.stats import CLIP_TOLERANCE

PERCENTILE_FIELDS = ("p1_ev", "p5_ev", "p50_ev", "p95_ev", "p99_ev")


def _grey(value: float, shape: tuple[int, int] = (40, 60)) -> np.ndarray:
    return np.full((*shape, 3), value, dtype=np.float32)


def _scene(seed: int = 0, shape: tuple[int, int] = (300, 400)) -> np.ndarray:
    rng = np.random.default_rng(seed)
    ev = rng.normal(0.0, 2.0, size=(*shape, 1))
    tint = rng.uniform(0.5, 1.5, size=(*shape, 3))
    return (0.18 * 2.0**ev * tint).astype(np.float32)


@pytest.mark.parametrize(("value", "ev"), [(0.18, 0.0), (0.045, -2.0), (0.72, 2.0)])
def test_constant_image_percentiles_are_exact(value: float, ev: float) -> None:
    stats = photo_stats(_grey(value), clip_level=1.0)
    for field in PERCENTILE_FIELDS:
        assert getattr(stats, field) == pytest.approx(ev, abs=1e-5)
    assert stats.dynamic_range_ev == pytest.approx(0.0, abs=1e-5)
    assert stats.clipped == 0.0


def test_ramp_percentiles() -> None:
    # 101 grey pixels from -5 to +5 EV in 0.1 EV steps: percentile q lands on pixel q exactly.
    ev = np.linspace(-5.0, 5.0, 101)
    image = np.repeat((0.18 * 2.0**ev)[None, :, None], 3, axis=-1).astype(np.float32)
    stats = photo_stats(image, clip_level=100.0)
    expected = {"p1_ev": -4.9, "p5_ev": -4.5, "p50_ev": 0.0, "p95_ev": 4.5, "p99_ev": 4.9}
    for field, value in expected.items():
        assert getattr(stats, field) == pytest.approx(value, abs=1e-4)
    assert stats.dynamic_range_ev == pytest.approx(9.8, abs=1e-4)


def test_clipped_fraction() -> None:
    image = _grey(0.2, shape=(100, 100))
    image[:25, :, 0] = 4.0  # a quarter clipped in one channel only
    image[25:30, :] = 4.0 * (1.0 - CLIP_TOLERANCE / 2)  # within the tolerance: clipped
    image[30:35, :] = 4.0 * (1.0 - 2 * CLIP_TOLERANCE)  # below it: not clipped
    assert photo_stats(image, clip_level=4.0).clipped == pytest.approx(0.30)


def test_grey_has_no_chroma_and_colour_has_some() -> None:
    assert photo_stats(_grey(0.18), clip_level=1.0).mean_chroma == pytest.approx(0.0, abs=1e-4)
    red = _grey(0.0)
    red[..., 0] = 0.18
    assert photo_stats(red, clip_level=1.0).mean_chroma > 0.1


def test_p50_equals_median_ev() -> None:
    for shape in [(300, 400), (1000, 700)]:
        image = _scene(shape=shape)
        stats = photo_stats(image, clip_level=1.0)
        assert stats.p50_ev == pytest.approx(median_ev(image), abs=1e-6)


@settings(max_examples=25, deadline=None)
@given(st.integers(0, 2**32 - 1), st.integers(-4, 4))
def test_scaling_light_shifts_every_percentile(seed: int, stops: int) -> None:
    image = _scene(seed, shape=(60, 80))
    before = photo_stats(image, clip_level=1e6)
    after = photo_stats(image * np.float32(2.0**stops), clip_level=1e6)
    for field in PERCENTILE_FIELDS:
        assert getattr(after, field) == pytest.approx(getattr(before, field) + stops, abs=1e-4)
    assert after.dynamic_range_ev == pytest.approx(before.dynamic_range_ev, abs=1e-4)


def test_to_dict_is_json_ready_and_rounded() -> None:
    stats = PhotoStats(
        p1_ev=-3.123456,
        p5_ev=-2.0,
        p50_ev=0.0004,
        p95_ev=2.0,
        p99_ev=3.0,
        dynamic_range_ev=6.123456,
        clipped=0.0123456,
        mean_chroma=0.0456789,
    )
    data = json.loads(json.dumps(stats.to_dict()))
    assert data["p1_ev"] == -3.123
    assert data["p50_ev"] == 0.0
    assert data["dynamic_range_ev"] == 6.123
    assert data["clipped"] == 0.01235
    assert data["mean_chroma"] == 0.04568
    assert set(data) == {*PERCENTILE_FIELDS, "dynamic_range_ev", "clipped", "mean_chroma"}


def test_fast_on_a_proxy() -> None:
    image = np.random.default_rng(1).uniform(0.0, 2.0, size=(1152, 2048, 3)).astype(np.float32)
    photo_stats(image, clip_level=1.0)  # warm up
    timings = []
    for _ in range(5):
        start = time.perf_counter()
        photo_stats(image, clip_level=1.0)
        timings.append(time.perf_counter() - start)
    assert min(timings) < 0.05
