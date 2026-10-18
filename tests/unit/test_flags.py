import json

import numpy as np
import pytest

from picturesq.config import ExposureConfig, OutliersConfig
from picturesq.normalise import (
    PhotoStats,
    exposure_decision,
    exposure_flags,
    outlier_flags,
)
from picturesq.normalise.flags import EXPOSURE_CLAMPED, OUTLIER


def _grey(value: float) -> np.ndarray:
    return np.full((20, 30, 3), value, dtype=np.float32)


def _stats(median: float = 0.0, clipped: float = 0.0) -> PhotoStats:
    return PhotoStats(
        p1_ev=median - 4,
        p5_ev=median - 3,
        p50_ev=median,
        p95_ev=median + 2,
        p99_ev=median + 3,
        dynamic_range_ev=7.0,
        clipped=clipped,
        mean_chroma=0.05,
    )


def test_decision_without_correction_is_the_offset() -> None:
    decision = exposure_decision(_grey(0.001), ExposureConfig(offset_ev=2.0))
    assert (decision.ev, decision.correction_ev, decision.clamped) == (2.0, 0.0, False)
    assert exposure_flags(decision, ExposureConfig()) == []


def test_clamped_correction_is_flagged() -> None:
    config = ExposureConfig(offset_ev=0.0, correction=1.0, target_ev=0.0, max_correction_ev=2.0)
    decision = exposure_decision(_grey(0.18 / 64), config)  # wants +6 EV
    assert decision.clamped
    assert decision.correction_ev == pytest.approx(2.0)
    (flag,) = exposure_flags(decision, config)
    assert flag.name == EXPOSURE_CLAMPED
    assert flag.details["limit_ev"] == 2.0


def test_correction_within_the_limit_is_not_flagged() -> None:
    config = ExposureConfig(offset_ev=0.0, correction=1.0, target_ev=0.0, max_correction_ev=2.0)
    decision = exposure_decision(_grey(0.18 / 2), config)  # wants +1 EV
    assert not decision.clamped
    assert decision.ev == pytest.approx(1.0, abs=1e-5)
    assert exposure_flags(decision, config) == []


@pytest.mark.parametrize(
    ("median", "expected"),
    [(-2.5, ["min"]), (-2.0, []), (0.0, []), (3.0, []), (3.2, ["max"])],
)
def test_median_outside_its_range_is_an_outlier(median: float, expected: list[str]) -> None:
    flags = outlier_flags(_stats(median=median), OutliersConfig())
    assert [key for flag in flags for key in ("min", "max") if key in flag.details] == expected
    assert all(flag.name == OUTLIER and flag.details["stat"] == "p50_ev" for flag in flags)


def test_clipped_above_its_limit_is_an_outlier() -> None:
    assert outlier_flags(_stats(clipped=0.02), OutliersConfig()) == []
    (flag,) = outlier_flags(_stats(clipped=0.1), OutliersConfig())
    assert flag.details == {"stat": "clipped", "value": 0.1, "max": 0.02}


def test_one_flag_per_stat() -> None:
    flags = outlier_flags(_stats(median=-5.0, clipped=0.5), OutliersConfig())
    assert sorted(str(flag.details["stat"]) for flag in flags) == ["clipped", "p50_ev"]


def test_flags_are_json_ready() -> None:
    (flag,) = outlier_flags(_stats(median=-5.0), OutliersConfig())
    document = json.loads(json.dumps(flag.to_dict()))
    assert document["flag"] == "outlier"
    assert document["details"]["min"] == -2.0
