"""The agent grade workflow end to end on a real CC0 sample (M3's exit demo, #127).

An agent edits ``grade.adjustments`` in picturesq.yaml, runs ``picturesq preview`` and reads
the sheet: the photo's current column moves the way the edit says, against its neutral
column in the same sheet.
"""

import shutil
from pathlib import Path

import numpy as np
import pytest
import yaml
from numpy.typing import NDArray
from PIL import Image
from typer.testing import CliRunner

from picturesq.cli import app
from picturesq.preview.look_sheet import LABEL_LINES, PANEL_SIZE
from picturesq.preview.stage_sheet import panel_origin

pytestmark = pytest.mark.integration

NAME = "dji-fc4382.dng"
runner = CliRunner()


def _preview(project: Path, adjustments: dict[str, float]) -> tuple[NDArray, NDArray]:
    """Write the edit, render the sheet; the neutral and current tiles' centres (float)."""
    config = {"photos": {NAME: {"grade": {"adjustments": adjustments}}}}
    (project / "picturesq.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    sheet_path = project / "sheet.png"
    result = runner.invoke(app, ["preview", str(project), "--png", str(sheet_path)])
    assert result.exit_code == 0, result.output
    sheet = np.asarray(Image.open(sheet_path).convert("RGB"), dtype=np.float64)
    width, height = PANEL_SIZE

    def centre(index: int) -> NDArray:
        # The middle of the tile: clear of the current column's border and any letterbox.
        x, y = panel_origin(index, PANEL_SIZE, columns=2, label_lines=LABEL_LINES)
        return sheet[y + height // 4 : y + 3 * height // 4, x + width // 4 : x + 3 * width // 4]

    return centre(0), centre(1)


def _chroma(pixels: NDArray) -> float:
    return float(np.ptp(pixels, axis=-1).mean())


def test_adjustment_edits_move_the_preview_the_right_way(samples_dir: Path, tmp_path: Path) -> None:
    source = samples_dir / NAME
    if not source.is_file():
        pytest.skip(f"{NAME} not found in {samples_dir}")
    shutil.copy(source, tmp_path / NAME)

    neutral, warmer = _preview(tmp_path, {"warmth": 15})
    red_minus_blue = (warmer[..., 0] - warmer[..., 2]).mean()
    assert red_minus_blue > (neutral[..., 0] - neutral[..., 2]).mean() + 3

    neutral, brighter = _preview(tmp_path, {"exposure": 0.5})
    assert brighter.mean() > neutral.mean() + 5

    neutral, muted = _preview(tmp_path, {"saturation": -0.6})
    assert _chroma(muted) < 0.6 * _chroma(neutral)
