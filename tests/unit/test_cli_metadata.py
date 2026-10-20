"""`picturesq metadata` and the corrected dates in exports, with decode replaced by a synthetic
image and originals that are small TIFFs with a camera whose clock says 2000-07-07."""

import json
from pathlib import Path

import numpy as np
import pytest
import yaml
from PIL import Image
from PIL.ExifTags import IFD, Base
from typer.testing import CliRunner

from picturesq.cli import app
from picturesq.config import load_project_config
from picturesq.export import read_exif, replace_exif, sidecar_path
from picturesq.pipeline import export as pipeline_export

runner = CliRunner()

CONFIG = """\
export:
  outputs:
    web: {long_edge: 100, quality: 80}
    archive: {long_edge: null, quality: 90}
  enabled: [web, archive]
"""
CAMERA_TIME = "2000:07:07 10:00:00"


def _synthetic(*_args: object, **_kwargs: object) -> np.ndarray:
    ramp = np.linspace(0.0, 0.8, 120, dtype=np.float32)
    image = np.empty((80, 120, 3), dtype=np.float32)
    image[...] = ramp[None, :, None]
    return image


@pytest.fixture(autouse=True)
def fake_decode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline_export, "decode_original", _synthetic)
    monkeypatch.setenv("PICTURESQ_WORKERS", "1")


def _original(path: Path, time: str | None = CAMERA_TIME) -> None:
    exif = Image.Exif()
    exif[Base.Make] = "DJI"
    directory = exif.get_ifd(IFD.Exif)
    if time is not None:
        directory[Base.DateTimeOriginal] = time
        directory[Base.DateTimeDigitized] = time
        directory[Base.SubsecTimeOriginal] = "42"
    directory[Base.ISOSpeedRatings] = 400
    Image.new("RGB", (8, 8)).save(path, format="TIFF", exif=exif.tobytes())


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    _original(project / "a.dng")
    _original(project / "b.dng", "2000:07:07 10:30:00")
    _original(project / "c.dng", None)
    (project / "picturesq.yaml").write_text(CONFIG)
    return project


def _exif(path: Path) -> tuple[dict[int, object], dict[int, object]]:
    with Image.open(path) as image:
        exif = image.getexif()
        return dict(exif), dict(exif.get_ifd(IFD.Exif))


def _scan(jpeg: bytes) -> bytes:
    """The entropy-coded image data: from the start-of-scan marker on."""
    return jpeg[jpeg.index(b"\xff\xda") :]


def _non_exif_bytes(jpeg: bytes) -> bytes:
    exif = read_exif(jpeg)
    assert exif is not None
    return jpeg.replace(b"\xff\xe1" + (len(exif) + 2).to_bytes(2, "big") + exif, b"")


def _run(*args: object) -> str:
    result = runner.invoke(app, [str(a) for a in args])
    assert result.exit_code == 0, result.output
    return result.output


def test_export_without_metadata_settings_keeps_the_camera_dates(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _run("export", project)
    image, exif = _exif(project / "exports" / "web" / "a.jpg")
    assert exif[Base.DateTimeOriginal] == CAMERA_TIME
    assert Base.DateTime not in image
    assert Base.OffsetTimeOriginal not in exif
    sidecar = json.loads(sidecar_path(project / "exports" / "web" / "a.jpg").read_text())
    assert sidecar["metadata"] == {
        "camera_time": "2000-07-07T10:00:00",
        "capture_time": "2000-07-07T10:00:00",
        "time_zone": None,
    }
    assert sidecar["sidecar_version"] == 4


def test_shift_from_one_photo_then_export_writes_the_corrected_dates(tmp_path: Path) -> None:
    project = _project(tmp_path)
    output = _run("metadata", "shift", project, "--photo", "a.dng", "--actual", "2026-10-17 20:05")
    assert "+9598d 10:05:00" in output
    _run("metadata", "zone", project, "+01:00")
    config = load_project_config(project / "picturesq.yaml")
    assert config.metadata.time_shift == "+9598d 10:05:00"
    assert config.metadata.time_zone == "+01:00"
    assert config.export.outputs["web"].long_edge == 100  # the rest of the file is kept

    _run("export", project)
    for name, expected in (("a", "2026:10:17 20:05:00"), ("b", "2026:10:17 20:35:00")):
        image, exif = _exif(project / "exports" / "web" / f"{name}.jpg")
        assert exif[Base.DateTimeOriginal] == expected
        assert exif[Base.DateTimeDigitized] == expected
        assert image[Base.DateTime] == expected
        assert exif[Base.OffsetTime] == "+01:00"
        assert exif[Base.OffsetTimeOriginal] == "+01:00"
        assert exif[Base.OffsetTimeDigitized] == "+01:00"
        assert exif[Base.SubsecTimeOriginal] == "42"
        assert exif[Base.ISOSpeedRatings] == 400
    sidecar = json.loads(sidecar_path(project / "exports" / "archive" / "a.jpg").read_text())
    assert sidecar["metadata"] == {
        "camera_time": "2000-07-07T10:00:00",
        "capture_time": "2026-10-17T20:05:00",
        "time_zone": "+01:00",
    }
    # An original without a capture time gets no date, only the zone.
    _, no_date = _exif(project / "exports" / "web" / "c.jpg")
    assert Base.DateTimeOriginal not in no_date
    assert no_date[Base.OffsetTimeOriginal] == "+01:00"


def test_per_photo_capture_time_wins_and_is_not_recorded_as_a_render_override(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    _run("metadata", "shift", project, "--by", "+1d")
    _run("metadata", "time", project, "B.DNG", "2026-10-17T20:05:00")
    _run("export", project)
    assert _exif(project / "exports" / "web" / "a.jpg")[1][Base.DateTimeOriginal] == (
        "2000:07:08 10:00:00"
    )
    assert _exif(project / "exports" / "web" / "b.jpg")[1][Base.DateTimeOriginal] == (
        "2026:10:17 20:05:00"
    )
    sidecar = json.loads(sidecar_path(project / "exports" / "web" / "b.jpg").read_text())
    assert sidecar["config"]["photos"] == {}  # a capture time changes no pixel
    assert sidecar["metadata"]["capture_time"] == "2026-10-17T20:05:00"


def test_apply_rewrites_the_dates_and_leaves_the_image_data_alone(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _run("export", project)
    web = project / "exports" / "web" / "a.jpg"
    before = web.read_bytes()
    assert _exif(web)[1][Base.DateTimeOriginal] == CAMERA_TIME

    _run("metadata", "shift", project, "--photo", "a.dng", "--actual", "2026-10-17 20:05")
    _run("metadata", "zone", project, "+01:00")
    output = _run("metadata", "apply", project)
    assert "6 export(s), 6 rewritten, 0 failed" in output

    after = web.read_bytes()
    assert after != before
    assert _scan(after) == _scan(before)  # the entropy-coded data, byte for byte
    assert _non_exif_bytes(after) == _non_exif_bytes(before)  # and every other segment
    image, exif = _exif(web)
    assert exif[Base.DateTimeOriginal] == "2026:10:17 20:05:00"
    assert image[Base.DateTime] == "2026:10:17 20:05:00"
    assert exif[Base.OffsetTimeOriginal] == "+01:00"
    assert exif[Base.ISOSpeedRatings] == 400
    assert image[Base.Make] == "DJI"
    assert str(image[Base.Software]).startswith("picturesq")

    sidecar = json.loads(sidecar_path(web).read_text())
    assert sidecar["metadata"]["capture_time"] == "2026-10-17T20:05:00"
    assert sidecar["metadata"]["camera_time"] == "2000-07-07T10:00:00"

    # Applying again changes nothing; clearing the shift puts the camera's time back.
    assert "0 rewritten" in _run("metadata", "apply", project)
    _run("metadata", "shift", project, "--clear")
    _run("metadata", "apply", project, "--output", "web")
    restored = web.read_bytes()
    assert _scan(restored) == _scan(before)
    assert _exif(web)[1][Base.DateTimeOriginal] == CAMERA_TIME
    # The archive output was not named, so it keeps the corrected date.
    assert _exif(project / "exports" / "archive" / "a.jpg")[1][Base.DateTimeOriginal] == (
        "2026:10:17 20:05:00"
    )


def test_apply_matches_a_fresh_export(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _run("export", project)
    _run("metadata", "shift", project, "--by", "-1d2h30m")
    _run("metadata", "zone", project, "-05:00")
    _run("metadata", "apply", project)
    rewritten = {p.name: p.read_bytes() for p in (project / "exports").glob("*/*")}
    _run("export", project)
    assert {p.name: p.read_bytes() for p in (project / "exports").glob("*/*")} == rewritten


def test_apply_without_exports_is_an_error(tmp_path: Path) -> None:
    project = _project(tmp_path)
    result = runner.invoke(app, ["metadata", "apply", str(project)])
    assert result.exit_code == 1
    assert "no exported JPEGs" in result.output


def test_apply_reports_a_file_that_is_not_a_jpeg(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _run("export", project)
    (project / "exports" / "web" / "a.jpg").write_bytes(b"not a jpeg")
    result = runner.invoke(app, ["metadata", "apply", str(project)])
    assert result.exit_code == 1
    assert "a.jpg: FAILED" in result.output


def test_show_lists_camera_and_corrected_times(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _run("metadata", "shift", project, "--by", "+1h")
    _run("metadata", "time", project, "b.dng", "2026-10-17 20:05")
    table = _run("metadata", "show", project)
    assert "2000-07-07 10:00:00  2000-07-07 11:00:00  shifted" in table
    assert "2000-07-07 10:30:00  2026-10-17 20:05:00  set for this photo" in table
    assert "no time recorded" in table
    document = json.loads(_run("metadata", "show", project, "--json"))
    assert document["time_shift"] == "+0d 01:00:00"
    assert [p["capture_time"] for p in document["photos"]] == [
        "2000-07-07T11:00:00",
        "2026-10-17T20:05:00",
        None,
    ]


def test_shift_clear_and_per_photo_clear(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _run("metadata", "shift", project, "--by", "-0d 00:00:01")
    _run("metadata", "time", project, "a", "2026-10-17 20:05")
    _run("metadata", "shift", project, "--clear")
    _run("metadata", "time", project, "a.dng", "--clear")
    config = load_project_config(project / "picturesq.yaml")
    assert config.metadata.time_shift == "+0d 00:00:00"
    assert config.photo("a.dng").metadata.capture_time is None
    assert "photos: {}" in (project / "picturesq.yaml").read_text()  # nothing left to say
    assert yaml.safe_load((project / "picturesq.yaml").read_text())["photos"] == {}


@pytest.mark.parametrize(
    "args",
    [
        ["shift"],
        ["shift", "--by", "+1h", "--clear"],
        ["shift", "--photo", "a.dng"],
        ["shift", "--by", "soon"],
        ["shift", "--photo", "nope.dng", "--actual", "2026-10-17 20:05"],
        ["shift", "--photo", "a.dng", "--actual", "yesterday"],
        ["shift", "--photo", "a.dng", "--actual", "2026-10-17T20:05:00+01:00"],
        ["zone"],
        ["zone", "BST"],
        ["time", "a.dng"],
        ["time", "nope.dng", "2026-10-17 20:05"],
        ["apply", "--output", "nope"],
    ],
)
def test_bad_usage_exits_2_and_changes_nothing(tmp_path: Path, args: list[str]) -> None:
    project = _project(tmp_path)
    before = (project / "picturesq.yaml").read_text()
    result = runner.invoke(app, ["metadata", args[0], str(project), *args[1:]])
    assert result.exit_code == 2, result.output
    assert (project / "picturesq.yaml").read_text() == before


def test_shift_from_a_photo_without_a_time_is_an_error(tmp_path: Path) -> None:
    project = _project(tmp_path)
    result = runner.invoke(
        app, ["metadata", "shift", str(project), "--photo", "c.dng", "--actual", "2026-10-17 20:05"]
    )
    assert result.exit_code == 1
    assert "no capture time" in result.output


def test_a_shift_off_the_calendar_fails_that_photo_only(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _original(project / "a.dng", "9999:12:31 23:00:00")
    _run("metadata", "shift", project, "--by", "+1d")
    result = runner.invoke(app, ["export", str(project)])
    assert result.exit_code == 1
    assert "a.dng: FAILED" in result.output
    assert (project / "exports" / "web" / "b.jpg").exists()


def test_replace_exif_swaps_only_the_exif_segment(tmp_path: Path) -> None:
    path = tmp_path / "x.jpg"
    Image.new("RGB", (16, 16), "teal").save(path, format="JPEG", exif=b"")
    plain = path.read_bytes()
    assert read_exif(plain) is None
    block = b"Exif\x00\x00II*\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    with_exif = replace_exif(plain, block)
    assert read_exif(with_exif) == block
    assert _scan(with_exif) == _scan(plain)
    assert with_exif.startswith(plain[:2])
    twice = replace_exif(with_exif, block + b"\x00\x00")
    assert read_exif(twice) == block + b"\x00\x00"
    assert twice.count(b"Exif\x00\x00") == 1
    assert _scan(twice) == _scan(plain)
