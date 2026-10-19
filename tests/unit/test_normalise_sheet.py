"""The contact sheet of a normalised project: layout, captions and `--png`."""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from typer.testing import CliRunner

from picturesq.cli import app
from picturesq.config import ProjectConfig
from picturesq.normalise import ExposureDecision, Flag
from picturesq.pipeline import normalise as normalise_module
from picturesq.pipeline import proxy as proxy_module
from picturesq.pipeline.normalise import NormaliseResult
from picturesq.preview.normalise_sheet import (
    COLUMNS,
    FLAG_COLOUR,
    LABEL_LINES,
    PANEL_SIZE,
    caption,
    normalise_panel,
    normalise_sheet,
    render_panel_pixels,
)
from picturesq.preview.stage_sheet import Panel, compose_sheet, panel_origin, sheet_size
from tests.unit.test_normalise_command import BRIGHT, D65_INFO, FakeDecode, _neutral, _project


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeDecode:
    decode = FakeDecode()
    monkeypatch.setattr(proxy_module, "decode_original", decode)
    monkeypatch.setattr(normalise_module, "read_photo_info", lambda *_: D65_INFO)
    return decode


runner = CliRunner()
WHITE = np.full((30, 40, 3), 255, dtype=np.uint8)


def test_multi_line_labels_make_room() -> None:
    one = sheet_size(5, (50, 40), columns=2)
    two = sheet_size(5, (50, 40), columns=2, label_lines=2)
    assert two[0] == one[0]
    assert two[1] - one[1] == 3 * 20  # three rows, one more 20 px line each


def test_marked_panels_get_a_border_and_others_do_not() -> None:
    mark = (255, 0, 0)
    panels = [Panel("a\nplain", WHITE), Panel("b\nflagged", WHITE, mark=mark)]
    sheet = compose_sheet("title", panels, (40, 30), columns=2, label_lines=2)
    assert sheet.size == sheet_size(2, (40, 30), columns=2, label_lines=2)
    pixels = np.asarray(sheet)
    for index, marked in enumerate([False, True]):
        x, y = panel_origin(index, (40, 30), 2, label_lines=2)
        assert tuple(pixels[y + 15, x + 20]) == (255, 255, 255)  # the tile itself
        left, below = tuple(pixels[y + 15, x - 2]), tuple(pixels[y + 32, x + 20])
        assert (left == mark and below == mark) == marked
    # Captions of a marked panel are drawn in its colour.
    label = pixels[: panel_origin(1, (40, 30), 2, 2)[1], panel_origin(1, (40, 30), 2, 2)[0] :]
    assert (label == mark).all(axis=-1).any()


def _result(**fields: object) -> NormaliseResult:
    decision = ExposureDecision(ev=2.0, correction_ev=0.0, clamped=False)
    return NormaliseResult(name="a.dng", **{"exposure": decision, **fields})  # type: ignore[arg-type]


def test_captions() -> None:
    assert caption(_result()) == "a.dng · +2.00 EV\nno flags"
    flagged = _result(flags=[Flag("outlier", "dark"), Flag("wb_disagreement", "warm")])
    assert caption(flagged) == "a.dng · +2.00 EV\noutlier, wb_disagreement"
    overridden = _result(exposure=ExposureDecision(1.5, 0.0, False), overrides={"exposure_ev": 1.5})
    assert caption(overridden).startswith("a.dng · +1.50 EV (override)")
    assert caption(_result(exposure=None)).startswith("a.dng · normalise off")
    assert caption(_result(error="corrupt")) == "a.dng\nFAILED"


def test_panels_mark_flagged_and_failed_photos() -> None:
    assert normalise_panel(_result(), WHITE).mark is None
    assert normalise_panel(_result(flags=[Flag("outlier", "dark")]), WHITE).mark == FLAG_COLOUR
    failed = normalise_panel(_result(error="corrupt"), None)
    assert failed.mark == FLAG_COLOUR
    assert failed.pixels.shape == (PANEL_SIZE[1], PANEL_SIZE[0], 3)


def test_sheet_is_columns_wide() -> None:
    panels = [normalise_panel(_result(), WHITE)] * (COLUMNS + 1)
    sheet = normalise_sheet("t", panels)
    assert sheet.size == sheet_size(len(panels), PANEL_SIZE, COLUMNS, LABEL_LINES)


def test_render_panel_pixels_leaves_the_image_alone() -> None:
    image = _neutral(4 * BRIGHT, size=(120, 180))
    before = image.copy()
    pixels = render_panel_pixels(image, ProjectConfig())
    assert np.array_equal(image, before)
    assert pixels.dtype == np.uint8
    assert pixels.shape == (120, 180, 3)  # never upscaled
    assert 60 < np.median(pixels) < 200  # mid grey-ish, through the display transform


def test_png_option_writes_the_sheet(tmp_path: Path, fake: FakeDecode) -> None:
    project = _project(tmp_path, ("a.dng", "dark.dng", "broken.dng"))
    sheet = tmp_path / "out" / "sheet.png"
    result = runner.invoke(app, ["normalise", str(project), "--png", str(sheet)])
    assert result.exit_code == 1  # broken.dng failed; the sheet is still written
    assert f"wrote {sheet}" in result.stdout
    with Image.open(sheet) as image:
        assert image.format == "PNG"
        assert image.size == sheet_size(3, PANEL_SIZE, COLUMNS, LABEL_LINES)


def test_unwritable_png_exits_1(tmp_path: Path, fake: FakeDecode) -> None:
    project = _project(tmp_path)
    blocker = tmp_path / "file"
    blocker.write_text("")
    result = runner.invoke(app, ["normalise", str(project), "--png", str(blocker / "s.png")])
    assert result.exit_code == 1
    assert "cannot write" in result.stderr


def test_json_mode_prints_only_json(tmp_path: Path, fake: FakeDecode) -> None:
    project = _project(tmp_path)
    sheet = tmp_path / "sheet.png"
    result = runner.invoke(app, ["normalise", str(project), "--json", "--png", str(sheet)])
    assert result.exit_code == 0
    assert result.stdout.startswith("{")
    assert sheet.is_file()


def test_panels_are_the_neutral_render_whatever_the_look() -> None:
    """The sheet judges normalise: a project look or adjustments don't change it (and need
    no resolved look)."""
    image = np.full((60, 80, 3), 0.18, dtype=np.float32)
    graded = ProjectConfig.model_validate(
        {"grade": {"look": {"name": "cold/anything"}, "adjustments": {"exposure": 1.0}}}
    )
    assert np.array_equal(
        render_panel_pixels(image, graded), render_panel_pixels(image, ProjectConfig())
    )
