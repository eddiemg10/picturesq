"""The white balance check on CC0 samples (needs reference/samples, see scripts/fetch_samples.py).

Measured 2026-10-18 on half-size decodes (brightest / grey, Δmired from as-shot):
dji-fc4382 -13 / -34, fujifilm-x-s10 +25 / +8, fujifilm-xq1 -15 / -4,
pentax-k5iis +28 / +33, pentax-q7 -1 / +4, sony-ilme-fx3 +88 / +87.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from picturesq.config import WhiteBalanceConfig
from picturesq.config.project import DecodeConfig
from picturesq.decode import decode_original, read_photo_info
from picturesq.normalise import WhiteBalanceCheck, check_white_balance, white_balance_flags


def _check(samples_dir: Path, name: str) -> WhiteBalanceCheck:
    path = samples_dir / name
    if not path.is_file():
        pytest.skip(f"{name} not found in {samples_dir}")
    config = DecodeConfig()
    image = decode_original(path, config, half_size=True)
    return check_white_balance(image, read_photo_info(path, config), WhiteBalanceConfig())


def test_sony_sample_is_flagged(samples_dir: Path) -> None:
    check = _check(samples_dir, "sony-ilme-fx3.arw")
    assert check.disagrees
    (flag,) = white_balance_flags(check, WhiteBalanceConfig())
    assert "warmer" in flag.message


def test_tungsten_interior_leans_warm_but_is_not_flagged(samples_dir: Path) -> None:
    # Both estimates say the light is warmer than the camera assumed (the camera leaves
    # tungsten scenes a little warm on purpose), but the brightest one is under 30 mired.
    check = _check(samples_dir, "pentax-k5iis.dng")
    assert check.brightest is not None
    assert check.grey is not None
    assert 20.0 < check.brightest.delta_mired < 30.0
    assert check.grey.delta_mired > 25.0
    assert not check.disagrees


@pytest.mark.parametrize("name", ["dji-fc4382.dng", "fujifilm-xq1.raf", "fujifilm-x-s10.raf"])
def test_daylight_samples_are_not_flagged(samples_dir: Path, name: str) -> None:
    check = _check(samples_dir, name)
    assert check.reason is None
    assert not check.disagrees
