"""`picturesq preview` and the look sheet."""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from typer.testing import CliRunner

from picturesq.cli import app
from picturesq.config import ProjectConfig
from picturesq.config.look import Look
from picturesq.pipeline import normalise as normalise_module
from picturesq.pipeline import proxy as proxy_module
from picturesq.preview.look_sheet import (
    LABEL_LINES,
    PANEL_SIZE,
    render_variant,
    variants,
)
from picturesq.preview.stage_sheet import sheet_size
from tests.unit.test_normalise_command import D65_INFO, FakeDecode, _project

runner = CliRunner()


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeDecode:
    decode = FakeDecode()
    monkeypatch.setattr(proxy_module, "decode_original", decode)
    monkeypatch.setattr(normalise_module, "read_photo_info", lambda *_: D65_INFO)
    return decode


def _config(data: dict[str, object]) -> ProjectConfig:
    return ProjectConfig.model_validate(data)


def test_variants_without_a_grade(test_looks: dict[str, Look]) -> None:
    row = variants(_config({}), "a.dng", list(test_looks.values()), test_looks)
    assert [variant.label for variant in row] == [
        "neutral",
        "bw/test_mono 100 %",
        "cold/test_cool 100 %",
    ]
    assert row[0].look is None


def test_variants_use_the_photos_own_grade(test_looks: dict[str, Look]) -> None:
    config = _config(
        {
            "grade": {
                "look": {"name": "cold/test_cool", "intensity": 0.6, "parameters": {"fade": 0.1}}
            },
            "photos": {"a.dng": {"grade": {"adjustments": {"warmth": 5}}}},
        }
    )
    row = variants(config, "a.dng", list(test_looks.values()), test_looks)
    labels = [variant.label for variant in row]
    assert labels == [
        "neutral",
        "current: cold/test_cool 60 % + adjustments",
        "bw/test_mono 100 %",
        "cold/test_cool 60 %",
    ]
    current, mono, cool = row[1], row[2], row[3]
    assert current.current and current.adjustments.warmth == 5
    assert mono.adjustments.warmth == 5  # adjustments apply to every look
    assert cool.look is not None and cool.look.parameters == {"fade": 0.1}
    assert row[0].adjustments.warmth == 0  # the neutral render has none


def test_render_variant_keeps_the_proxy_and_differs_by_look(test_looks: dict[str, Look]) -> None:
    image = np.random.default_rng(0).lognormal(np.log(0.18), 1.0, (300, 400, 3)).astype(np.float32)
    before = image.copy()
    row = variants(_config({}), "a.dng", list(test_looks.values()), test_looks)
    pixels = [render_variant(image, _config({}), "a.dng", None, variant) for variant in row]
    assert np.array_equal(image, before)
    assert pixels[0].shape == (270, 360, 3)
    neutral, mono, cool = pixels
    assert np.ptp(mono.astype(int), axis=-1).max() <= 1  # black and white
    assert not np.array_equal(neutral, cool)


def test_preview_writes_the_default_sheet(
    tmp_path: Path, fake: FakeDecode, test_looks: dict[str, Look]
) -> None:
    project = _project(tmp_path)
    result = runner.invoke(app, ["preview", str(project)])
    assert result.exit_code == 0, result.output
    path = project / ".picturesq" / "previews" / "sheet.png"
    assert f"wrote {path}" in result.stdout
    with Image.open(path) as sheet:
        # Two photos x (neutral + two looks).
        assert sheet.size == sheet_size(6, PANEL_SIZE, 3, LABEL_LINES)
    assert not (project / "picturesq.yaml").exists()


def test_preview_category_and_looks(
    tmp_path: Path, fake: FakeDecode, test_looks: dict[str, Look]
) -> None:
    project = _project(tmp_path, ("a.dng",))
    png = tmp_path / "bw.png"
    result = runner.invoke(app, ["preview", str(project), "--category", "bw", "--png", str(png)])
    assert result.exit_code == 0, result.output
    with Image.open(png) as sheet:
        assert sheet.size == sheet_size(2, PANEL_SIZE, 2, LABEL_LINES)
    chosen = runner.invoke(
        app, ["preview", str(project), "--look", "cold/test_cool", "--png", str(png)]
    )
    assert chosen.exit_code == 0, chosen.output
    unknown = runner.invoke(app, ["preview", str(project), "--look", "cold/nope"])
    assert unknown.exit_code == 2
    assert "no look called 'cold/nope'" in unknown.output


def test_preview_marks_a_failed_photo(
    tmp_path: Path, fake: FakeDecode, test_looks: dict[str, Look]
) -> None:
    project = _project(tmp_path, ("a.dng", "broken.dng"))
    result = runner.invoke(app, ["preview", str(project), "--category", "bw"])
    assert result.exit_code == 1
    assert "1 photo(s) failed" in result.output
    assert (project / ".picturesq" / "previews" / "sheet.png").is_file()
