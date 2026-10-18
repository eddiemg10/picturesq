"""Looks on real CC0 samples: no look and intensity 0 are byte-identical exports, and a
photo's look override changes only that photo."""

from pathlib import Path

import pytest

from picturesq.config import ProjectConfig
from picturesq.config.look import Look
from picturesq.pipeline.export import export_originals

pytestmark = pytest.mark.integration

NAMES = ("dji-fc4382.dng", "pentax-q7.dng")
WEB_ONLY = {"export": {"enabled": ["web"]}}


def _originals(samples_dir: Path) -> list[Path]:
    originals = []
    for name in NAMES:
        source = samples_dir / name
        if not source.is_file():
            pytest.skip(f"{name} not found in {samples_dir}")
        originals.append(source)
    return originals


def _export(originals: list[Path], config: dict[str, object], out: Path) -> dict[str, bytes]:
    result = export_originals(originals, ProjectConfig.model_validate({**WEB_ONLY, **config}), out)
    assert result.failed == 0, [photo.error for photo in result.photos]
    return {path.name: path.read_bytes() for path in sorted((out / "web").glob("*.jpg"))}


def test_no_look_and_intensity_zero_are_the_neutral_render(
    samples_dir: Path, tmp_path: Path, test_looks: dict[str, Look]
) -> None:
    originals = _originals(samples_dir)
    neutral = _export(originals, {}, tmp_path / "neutral")
    zero = _export(
        originals,
        {"grade": {"look": {"name": "cold/test_cool", "intensity": 0.0}}},
        tmp_path / "zero",
    )
    assert zero == neutral


def test_a_photos_look_override_changes_only_that_photo(
    samples_dir: Path, tmp_path: Path, test_looks: dict[str, Look]
) -> None:
    originals = _originals(samples_dir)
    neutral = _export(originals, {}, tmp_path / "neutral")
    overridden = _export(
        originals,
        {"photos": {NAMES[0]: {"grade": {"look": {"name": "bw/test_mono"}}}}},
        tmp_path / "override",
    )
    first, second = (f"{Path(name).stem}.jpg" for name in NAMES)
    assert overridden[first] != neutral[first]
    assert overridden[second] == neutral[second]
    sidecar = (tmp_path / "override" / "web" / f"{Path(NAMES[0]).stem}.picturesq.json").read_text()
    assert '"name": "bw/test_mono"' in sidecar
