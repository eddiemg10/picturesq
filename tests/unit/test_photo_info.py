"""Photo info: as-shot white and clip level, from synthetic inputs."""

from __future__ import annotations

import json
from pathlib import Path

import colour
import numpy as np
import pytest

from picturesq.colour.spaces import XYZ_TO_REC2020
from picturesq.colour.temperature import xy_to_xyz
from picturesq.config.project import DecodeConfig
from picturesq.decode import DecodeError, PhotoInfo, read_photo_info
from picturesq.decode.info import _duv, clip_level, multipliers_to_xy

MULTIPLIERS = np.array([2.0, 1.0, 1.5])


def test_clip_mode_clips_white_at_the_gain() -> None:
    assert clip_level(MULTIPLIERS, "clip", 1.0) == 1.0
    assert clip_level(MULTIPLIERS, "clip", 2.0**0.5) == pytest.approx(2.0**0.5)


def test_ignore_mode_keeps_neutrals_up_to_the_smallest_multiplier() -> None:
    assert clip_level(MULTIPLIERS, "ignore", 2.0) == pytest.approx(2.0 * 1.0 / 2.0)


def test_blend_mode_keeps_the_mean_of_the_channels() -> None:
    assert clip_level(MULTIPLIERS, "blend", 1.0) == pytest.approx(1.5 / 2.0)


def test_reconstruct_mode_tops_out_near_the_gain() -> None:
    assert clip_level(MULTIPLIERS, "reconstruct", 1.5) == 1.5


def test_equal_multipliers_clip_at_the_gain_in_every_mode() -> None:
    for mode in ("clip", "ignore", "blend", "reconstruct"):
        assert clip_level(np.ones(3), mode, 1.0) == pytest.approx(1.0)


def test_unknown_highlight_mode_is_an_error() -> None:
    with pytest.raises(ValueError, match="highlight mode"):
        clip_level(MULTIPLIERS, "magic", 1.0)


def test_multipliers_find_the_white_they_neutralise() -> None:
    # A "camera" whose RGB is linear Rec.2020: the multipliers that neutralise tungsten
    # (standard light A) are the inverse of A's camera RGB.
    cam_xyz = XYZ_TO_REC2020
    tungsten = (0.44757, 0.40745)
    multipliers = 1.0 / (cam_xyz @ xy_to_xyz(tungsten))
    xy = multipliers_to_xy(multipliers * 7.0, cam_xyz)  # only the ratios matter
    assert xy == pytest.approx(tungsten, abs=1e-9)


@pytest.mark.parametrize(
    "xy",
    [
        (0.3127, 0.3290),  # D65, a little above the black-body line (greener)
        (0.44757, 0.40745),  # standard light A, on the line
        (0.3457, 0.3585),  # D50
        (0.38, 0.40),  # green of the line
        (0.38, 0.36),  # magenta of the line
        (0.30, 0.30),
        (0.50, 0.41),
    ],
)
def test_duv_matches_colour_science(xy: tuple[float, float]) -> None:
    uv = colour.xy_to_UCS_uv(np.array(xy))
    expected = colour.temperature.uv_to_CCT_Ohno2013(uv)[1]
    assert _duv(xy) == pytest.approx(expected, abs=2e-4)


def test_duv_sign_is_positive_above_the_line() -> None:
    assert _duv((0.3127, 0.3290)) > 0.0  # D65's Duv is about +0.0032
    assert _duv((0.38, 0.36)) < 0.0


def test_photo_info_is_json_ready() -> None:
    info = PhotoInfo(
        as_shot_xy=(np.float64(0.3127), 0.329),  # type: ignore[arg-type]
        as_shot_kelvin=6504.123456789,
        as_shot_tint=-3.2,
        baseline_exposure_ev=0.5,
        clip_level=np.float64(1.4142135623),  # type: ignore[arg-type]
    )
    data = info.to_dict()
    assert json.loads(json.dumps(data)) == data
    assert data["as_shot_xy"] == [0.3127, 0.329]
    assert data["as_shot_kelvin"] == 6504.123457
    assert data["clip_level"] == 1.414214


def test_unknown_white_is_none_in_json() -> None:
    info = PhotoInfo(None, None, None, 0.0, 1.0)
    assert info.to_dict()["as_shot_xy"] is None


def test_non_raw_file_raises_decode_error(tmp_path: Path) -> None:
    junk = tmp_path / "junk.raf"
    junk.write_bytes(b"not a raw file" * 100)
    with pytest.raises(DecodeError):
        read_photo_info(junk, DecodeConfig())


def test_missing_file_raises_decode_error(tmp_path: Path) -> None:
    with pytest.raises(DecodeError):
        read_photo_info(tmp_path / "missing.dng", DecodeConfig())
