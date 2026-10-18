"""`picturesq normalise` and the per-photo computation behind it, on synthetic proxies."""

import json
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from picturesq.cli import app
from picturesq.config import DecodeConfig, ProjectConfig
from picturesq.decode import DecodeError, PhotoInfo
from picturesq.normalise.exposure import linear_to_ev
from picturesq.pipeline import normalise as normalise_module
from picturesq.pipeline import proxy as proxy_module
from picturesq.pipeline.normalise import (
    STATS_DIRNAME,
    NormaliseResult,
    normalise_proxy,
    summarise,
    unmatched_overrides,
    write_stats,
)
from picturesq.pipeline.proxy import CACHE_DIRNAME

runner = CliRunner()
D65_INFO = PhotoInfo((0.3127, 0.3290), 6504.0, 0.0, 0.0, 1.0)
"""A daylight as-shot white: a neutral surface decodes to R = G = B."""
BRIGHT = 0.05
"""Median of the bright synthetic photo: +2 EV makes it 0.2, just above mid grey."""
DARK = 0.005
"""Median of the dark one: 0.02 after +2 EV, about -3.2 EV, an outlier."""


def _neutral(level: float, size: tuple[int, int] = (200, 300), seed: int = 0) -> np.ndarray:
    """A grey image whose luminance is spread around ``level`` (so the estimators find pixels)."""
    rng = np.random.default_rng(seed)
    values = level * rng.lognormal(0.0, 0.6, size).astype(np.float32)
    return np.repeat(values[..., None], 3, axis=-1).astype(np.float32)


def _config(yaml_like: dict[str, object] | None = None) -> ProjectConfig:
    return ProjectConfig.model_validate(yaml_like or {})


# --- normalise_proxy --------------------------------------------------------------------------


def test_neutral_photo_is_exposed_measured_and_unflagged() -> None:
    result = normalise_proxy(_neutral(BRIGHT), "a.dng", D65_INFO, _config())
    assert result.error is None
    assert result.exposure is not None
    assert result.exposure.ev == pytest.approx(2.0)
    assert result.stats is not None
    assert result.stats.p50_ev == pytest.approx(linear_to_ev(4 * BRIGHT), abs=0.05)
    assert result.white_balance is not None
    assert result.white_balance.reason is None
    assert not result.white_balance.disagrees
    assert result.flags == []
    assert result.overrides == {}


def test_dark_photo_is_an_outlier() -> None:
    result = normalise_proxy(_neutral(DARK), "a.dng", D65_INFO, _config())
    assert [flag.name for flag in result.flags] == ["outlier"]
    assert result.flags[0].details["stat"] == "p50_ev"


CLAMPING: dict[str, object] = {
    "normalise": {"exposure": {"correction": 1.0, "target_ev": 3.0, "max_correction_ev": 0.5}}
}


def test_clamped_correction_is_flagged() -> None:
    result = normalise_proxy(_neutral(BRIGHT), "a.dng", D65_INFO, _config(CLAMPING))
    assert result.exposure is not None
    assert result.exposure.clamped
    assert result.exposure.ev == pytest.approx(2.5)
    assert "exposure_clamped" in [flag.name for flag in result.flags]


def test_exposure_override_replaces_the_decision_and_is_never_clamped() -> None:
    config = _config({**CLAMPING, "photos": {"A.DNG": {"normalise": {"exposure_ev": 1.25}}}})
    result = normalise_proxy(_neutral(BRIGHT), "a.dng", D65_INFO, config)
    assert result.exposure is not None
    assert result.exposure.ev == 1.25
    assert result.overrides == {"exposure_ev": 1.25}
    assert result.flags == []
    assert result.to_dict()["exposure_ev"] == 1.25


def test_disabled_photo_reports_unnormalised_stats_and_no_exposure_flag() -> None:
    config = _config({**CLAMPING, "photos": {"a.dng": {"normalise": {"enabled": False}}}})
    image = _neutral(BRIGHT)
    before = image.copy()
    result = normalise_proxy(image, "a.dng", D65_INFO, config)
    assert result.exposure is None
    assert not result.normalised
    assert np.array_equal(image, before)
    assert result.stats is not None
    assert result.stats.p50_ev == pytest.approx(linear_to_ev(BRIGHT), abs=0.05)
    assert "exposure_clamped" not in [flag.name for flag in result.flags]
    document = result.to_dict()
    assert document["normalised"] is False
    assert document["exposure_ev"] is None


def test_clip_level_follows_the_exposure() -> None:
    # 10 % of the pixels sit at the clip level (1.0): still clipped after +2 EV (4.0).
    image = _neutral(BRIGHT)
    image[:20] = 1.0
    result = normalise_proxy(image, "a.dng", D65_INFO, _config())
    assert result.stats is not None
    assert result.stats.clipped == pytest.approx(0.1, abs=0.005)


def _warm(level: float) -> np.ndarray:
    """A grey scene lit by a much warmer light than the as-shot white."""
    image = _neutral(level)
    image *= np.array([1.6, 1.0, 0.55], dtype=np.float32)
    return image


def test_white_balance_disagreement_is_flagged() -> None:
    result = normalise_proxy(_warm(BRIGHT), "a.dng", D65_INFO, _config())
    assert result.white_balance is not None
    assert result.white_balance.disagrees
    assert "wb_disagreement" in [flag.name for flag in result.flags]


def test_white_balance_override_reports_the_check_but_does_not_flag() -> None:
    config = _config({"photos": {"a.dng": {"normalise": {"wb_kelvin": 3000}}}})
    result = normalise_proxy(_warm(BRIGHT), "a.dng", D65_INFO, config)
    assert result.white_balance is not None
    assert result.white_balance.disagrees  # checked on the decoded proxy, before the override
    assert "wb_disagreement" not in [flag.name for flag in result.flags]
    assert result.overrides == {"wb_kelvin": 3000.0}


# --- summary and stats files ------------------------------------------------------------------


def _results() -> list[NormaliseResult]:
    config = _config()
    return [
        normalise_proxy(_neutral(BRIGHT), "a.dng", D65_INFO, config),
        normalise_proxy(_neutral(DARK), "b.dng", D65_INFO, config),
        NormaliseResult(name="c.dng", error="cannot decode c.dng: corrupt"),
    ]


def test_summary_counts_flags_and_the_spread_of_medians() -> None:
    results = _results()
    summary = summarise(results, ["typo.dng"])
    assert summary["photos"] == 3
    assert summary["failed"] == 1
    assert summary["failed_photos"] == ["c.dng"]
    assert summary["flagged"] == 1
    assert summary["flagged_photos"] == ["b.dng"]
    assert summary["flags"] == {"outlier": 1}
    medians = [r.stats.p50_ev for r in results if r.stats is not None]
    assert summary["median_ev"]["spread"] == pytest.approx(max(medians) - min(medians), abs=1e-3)
    assert summary["median_ev"]["min"] < summary["median_ev"]["median"]
    assert summary["unmatched_overrides"] == ["typo.dng"]


def test_summary_without_stats_has_no_medians() -> None:
    assert summarise([NormaliseResult(name="a.dng", error="x")])["median_ev"] is None


def test_stats_files_are_deterministic_and_stale_ones_removed(tmp_path: Path) -> None:
    folder = tmp_path / STATS_DIRNAME
    folder.mkdir()
    (folder / "gone.json").write_text("{}")
    results = _results()
    write_stats(results, summarise(results), tmp_path)
    names = sorted(p.name for p in folder.iterdir())
    assert names == ["a.json", "b.json", "c.json", "summary.json"]
    first = {name: (folder / name).read_bytes() for name in names}
    write_stats(results, summarise(results), tmp_path)
    assert {name: (folder / name).read_bytes() for name in names} == first
    a = json.loads(first["a.json"])
    assert a["version"]
    assert a["photo"] == "a.dng"
    assert list(a) == sorted(a)
    assert str(tmp_path) not in first["a.json"].decode()
    assert json.loads(first["c.json"])["error"] == "cannot decode c.dng: corrupt"


def test_unmatched_overrides_ignore_case() -> None:
    config = _config({"photos": {"A.DNG": {}, "typo.dng": {}}})
    assert unmatched_overrides(config, [Path("a.dng"), Path("b.dng")]) == ["typo.dng"]


# --- `picturesq normalise` --------------------------------------------------------------------


class FakeDecode:
    """Decodes ``dark*`` originals to a dark grey image, the rest to a bright one."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, path: Path, config: DecodeConfig, *, half_size: bool = False) -> np.ndarray:
        self.calls.append(path.name)
        if path.stem == "broken":
            raise DecodeError(f"cannot decode {path.name}: corrupt")
        return _neutral(DARK if path.stem.startswith("dark") else BRIGHT)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeDecode:
    decode = FakeDecode()
    monkeypatch.setattr(proxy_module, "decode_original", decode)
    monkeypatch.setattr(normalise_module, "read_photo_info", lambda *_: D65_INFO)
    return decode


def _project(tmp_path: Path, names: tuple[str, ...] = ("a.dng", "b.dng")) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    for name in names:
        (project / name).write_bytes(b"raw " + name.encode())
    return project


def test_json_contract_and_stats_files(tmp_path: Path, fake: FakeDecode) -> None:
    project = _project(tmp_path)
    result = runner.invoke(app, ["normalise", str(project), "--json"])
    assert result.exit_code == 0, result.output
    document = json.loads(result.stdout)
    assert set(document) == {"version", "photos", "summary"}
    photo = document["photos"][0]
    assert set(photo) == {
        "photo",
        "proxy_key",
        "normalised",
        "exposure_ev",
        "correction_ev",
        "overrides",
        "info",
        "stats",
        "white_balance",
        "flags",
        "error",
    }
    assert photo["photo"] == "a.dng"
    assert photo["exposure_ev"] == 2.0
    assert set(photo["stats"]) >= {"p50_ev", "clipped", "mean_chroma"}
    summary = document["summary"]
    assert summary["photos"] == 2
    assert summary["flagged"] == 0
    assert "seconds" in summary

    stats = project / CACHE_DIRNAME / STATS_DIRNAME
    saved = json.loads((stats / "a.json").read_text())
    assert saved == {"version": document["version"], **photo}
    saved_summary = json.loads((stats / "summary.json").read_text())
    without_time = {key: value for key, value in summary.items() if key != "seconds"}
    assert saved_summary == {"version": document["version"], **without_time}
    assert not (project / "picturesq.yaml").exists()
    assert len(list((project / CACHE_DIRNAME / "proxies").iterdir())) == 2


def test_proxies_are_reused(tmp_path: Path, fake: FakeDecode) -> None:
    project = _project(tmp_path)
    assert runner.invoke(app, ["normalise", str(project)]).exit_code == 0
    assert runner.invoke(app, ["normalise", str(project)]).exit_code == 0
    assert fake.calls == ["a.dng", "b.dng"]


def test_text_output_and_strict(tmp_path: Path, fake: FakeDecode) -> None:
    project = _project(tmp_path, ("a.dng", "dark.dng"))
    result = runner.invoke(app, ["normalise", str(project)])
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0].startswith("a.dng     exposure +2.00 EV  median")
    assert lines[0].endswith("ok")
    assert "as-shot 6504 K" in lines[0]
    assert lines[1].startswith("dark.dng  ") and lines[1].endswith("outlier")
    assert lines[2].strip().startswith("outlier: median")
    assert lines[-1].startswith("2 photo(s): 1 flagged, 0 failed; medians")

    strict = runner.invoke(app, ["normalise", str(project), "--strict"])
    assert strict.exit_code == 3
    assert strict.stdout.splitlines()[:-1] == lines[:-1]  # printed in full, then exit 3


def test_strict_without_flags_exits_0(tmp_path: Path, fake: FakeDecode) -> None:
    project = _project(tmp_path)
    assert runner.invoke(app, ["normalise", str(project), "--strict"]).exit_code == 0


def test_a_failed_photo_exits_1_and_the_others_are_measured(
    tmp_path: Path, fake: FakeDecode
) -> None:
    project = _project(tmp_path, ("a.dng", "broken.dng", "dark.dng"))
    result = runner.invoke(app, ["normalise", str(project), "--json", "--strict"])
    assert result.exit_code == 1
    document = json.loads(result.stdout)
    broken = document["photos"][1]
    assert "corrupt" in broken["error"]
    assert broken["stats"] is None
    assert document["summary"]["failed_photos"] == ["broken.dng"]
    stats = project / CACHE_DIRNAME / STATS_DIRNAME
    assert json.loads((stats / "dark.json").read_text())["stats"] is not None


def test_override_naming_no_original_warns(tmp_path: Path, fake: FakeDecode) -> None:
    project = _project(tmp_path)
    (project / "picturesq.yaml").write_text("photos:\n  typo.dng: {normalise: {exposure_ev: 1}}\n")
    result = runner.invoke(app, ["normalise", str(project), "--json"])
    assert result.exit_code == 0
    assert "warning: photos: typo.dng names no original" in result.stderr
    assert json.loads(result.stdout)["summary"]["unmatched_overrides"] == ["typo.dng"]


def test_photo_named_summary_fails_without_overwriting_the_summary(
    tmp_path: Path, fake: FakeDecode
) -> None:
    project = _project(tmp_path, ("a.dng", "summary.dng"))
    result = runner.invoke(app, ["normalise", str(project), "--json"])
    assert result.exit_code == 1
    assert "rename it" in json.loads(result.stdout)["photos"][1]["error"]
    summary = project / CACHE_DIRNAME / STATS_DIRNAME / "summary.json"
    assert json.loads(summary.read_text())["photos"] == 2


@pytest.mark.parametrize(
    ("yaml", "names", "code"),
    [("decode: {proxy_long_edge: 10}\n", ("a.dng",), 2), ("", ("a.dng", "a.arw"), 1), ("", (), 1)],
)
def test_invalid_config_collisions_and_empty_projects(
    tmp_path: Path, fake: FakeDecode, yaml: str, names: tuple[str, ...], code: int
) -> None:
    project = _project(tmp_path, names)
    if yaml:
        (project / "picturesq.yaml").write_text(yaml)
    assert runner.invoke(app, ["normalise", str(project)]).exit_code == code
    assert fake.calls == []


def test_missing_project_exits_2(tmp_path: Path) -> None:
    assert runner.invoke(app, ["normalise", str(tmp_path / "nope")]).exit_code == 2
