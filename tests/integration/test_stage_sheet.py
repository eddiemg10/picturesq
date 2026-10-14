"""scripts/stage_sheet.py end to end on a CC0 sample (needs reference/samples)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]


def test_sheet_renders_for_dji_sample(samples_dir: Path, tmp_path: Path) -> None:
    if not (samples_dir / "dji-fc4382.dng").exists():
        pytest.skip("dji-fc4382.dng not found")
    out = tmp_path / "sheet.jpg"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "stage_sheet.py"), "--out", str(out)],
        capture_output=True,
        text=True,
        env={**os.environ, "PICTURESQ_SAMPLES": str(samples_dir)},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    with Image.open(out) as sheet:
        assert sheet.width <= 1600
    assert "BaselineExposure: +1.32 EV" in result.stdout
