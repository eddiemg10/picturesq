"""`picturesq normalise` on two CC0 samples (needs reference/samples, see scripts/fetch_samples.py).

Measured 2026-10-18 (default config, proxies): dji-fc4382 median -1.30 EV, no flag;
sony-ilme-fx3 median -2.53 EV, flagged outlier (median below -2 EV: a dark scene the camera
brightened more than we do). Its white balance check disagrees (both estimates ~85 mired warmer
than as-shot) and is recorded in the stats, but wb_disagreement is off by default.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from picturesq.cli import app
from picturesq.pipeline.normalise import STATS_DIRNAME
from picturesq.pipeline.proxy import CACHE_DIRNAME

pytestmark = pytest.mark.integration

NAMES = ("dji-fc4382.dng", "sony-ilme-fx3.arw")


def test_normalise_two_samples(samples_dir: Path, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    for name in NAMES:
        if not (samples_dir / name).is_file():
            pytest.skip(f"{name} not found in {samples_dir}")
        (project / name).symlink_to(samples_dir / name)

    result = CliRunner().invoke(app, ["normalise", str(project), "--json", "--strict"])
    assert result.exit_code == 3, result.output
    document = json.loads(result.stdout)
    dji, sony = document["photos"]
    assert dji["error"] is None and sony["error"] is None
    assert dji["flags"] == []
    assert -2.0 < dji["stats"]["p50_ev"] < 0.0
    assert {flag["flag"] for flag in sony["flags"]} == {"outlier"}
    assert sony["white_balance"]["disagrees"]
    assert document["summary"]["flagged_photos"] == ["sony-ilme-fx3.arw"]

    stats = project / CACHE_DIRNAME / STATS_DIRNAME
    assert sorted(p.name for p in stats.iterdir()) == [
        "dji-fc4382.json",
        "sony-ilme-fx3.json",
        "summary.json",
    ]
    sony_stats = json.loads((stats / "sony-ilme-fx3.json").read_text())
    assert sony_stats["white_balance"]["disagrees"]  # recorded even with the flag off
    assert not (project / "picturesq.yaml").exists()
