"""`picturesq run` / `export` end to end, with decode replaced by a synthetic image."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from typer.testing import CliRunner

from picturesq.cli import app
from picturesq.decode import DecodeError
from picturesq.pipeline import export as pipeline_export

runner = CliRunner()

CONFIG = """\
export:
  outputs:
    web: {long_edge: 100, quality: 80}
    archive: {long_edge: null, quality: 90}
  enabled: [web, archive]
"""


def _synthetic(*_args: object, **_kwargs: object) -> np.ndarray:
    ramp = np.linspace(0.0, 0.8, 300, dtype=np.float32)
    image = np.empty((200, 300, 3), dtype=np.float32)
    image[...] = ramp[None, :, None]
    return image


@pytest.fixture(autouse=True)
def fake_decode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline_export, "decode_original", _synthetic)


def _project(
    tmp_path: Path, names: tuple[str, ...] = ("a.dng", "b.dng"), config: bool = True
) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    for name in names:
        (project / name).write_bytes(b"not really a raw " + name.encode())
    if config:
        (project / "picturesq.yaml").write_text(CONFIG)
    return project


def _hashes(project: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in project.glob("*.dng")}


def test_run_writes_outputs_with_sizes_and_icc(tmp_path: Path) -> None:
    project = _project(tmp_path)
    before = _hashes(project)
    result = runner.invoke(app, ["run", str(project)])
    assert result.exit_code == 0, result.output
    for stem in ("a", "b"):
        with Image.open(project / "exports" / "web" / f"{stem}.jpg") as web:
            assert web.size == (100, 67)
            assert web.info.get("icc_profile")
        with Image.open(project / "exports" / "archive" / f"{stem}.jpg") as archive:
            assert archive.size == (300, 200)
    assert _hashes(project) == before


def test_json_output(tmp_path: Path) -> None:
    project = _project(tmp_path)
    result = runner.invoke(app, ["run", str(project), "--json"])
    assert result.exit_code == 0, result.output
    document = json.loads(result.stdout)
    assert [p["photo"] for p in document["photos"]] == ["a.dng", "b.dng"]
    first = document["photos"][0]
    assert set(first) == {"photo", "outputs", "error", "seconds"}
    assert first["error"] is None
    assert first["outputs"]["web"].endswith("exports/web/a.jpg")
    assert document["summary"]["photos"] == 2
    assert document["summary"]["failed"] == 0


def test_out_redirects(tmp_path: Path) -> None:
    project = _project(tmp_path)
    out = tmp_path / "elsewhere"
    result = runner.invoke(app, ["export", str(project), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert (out / "web" / "a.jpg").exists()
    assert not (project / "exports").exists()


def test_output_filter(tmp_path: Path) -> None:
    project = _project(tmp_path)
    result = runner.invoke(app, ["export", str(project), "--output", "web"])
    assert result.exit_code == 0, result.output
    assert (project / "exports" / "web" / "a.jpg").exists()
    assert not (project / "exports" / "archive").exists()


def test_unknown_output_exits_2(tmp_path: Path) -> None:
    project = _project(tmp_path)
    result = runner.invoke(app, ["export", str(project), "--output", "nope"])
    assert result.exit_code == 2
    assert not (project / "exports").exists()


def test_invalid_yaml_exits_2(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "picturesq.yaml").write_text("export: [not, a, mapping]\n")
    assert runner.invoke(app, ["run", str(project)]).exit_code == 2
    assert runner.invoke(app, ["export", str(project)]).exit_code == 2


def test_missing_project_exits_2(tmp_path: Path) -> None:
    assert runner.invoke(app, ["run", str(tmp_path / "nope")]).exit_code == 2


def test_empty_project_exits_1(tmp_path: Path) -> None:
    project = _project(tmp_path, names=())
    assert runner.invoke(app, ["run", str(project)]).exit_code == 1


def test_failed_decode_is_reported_and_others_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)

    def flaky(path: Path, *_a: object, **_k: object) -> np.ndarray:
        if path.name == "a.dng":
            raise DecodeError("cannot decode a.dng: corrupt")
        return _synthetic()

    monkeypatch.setattr(pipeline_export, "decode_original", flaky)
    result = runner.invoke(app, ["run", str(project), "--json"])
    assert result.exit_code == 1
    document = json.loads(result.stdout)
    assert "corrupt" in document["photos"][0]["error"]
    assert document["photos"][0]["outputs"] == {}
    assert document["photos"][1]["error"] is None
    assert document["summary"]["failed"] == 1
    assert (project / "exports" / "web" / "b.jpg").exists()
    assert not (project / "exports" / "web" / "a.jpg").exists()


def test_stem_collision_fails_before_writing(tmp_path: Path) -> None:
    project = _project(tmp_path, names=("A.NEF", "A.dng"))
    result = runner.invoke(app, ["run", str(project)])
    assert result.exit_code == 1
    assert "share the name" in result.output
    assert not (project / "exports").exists()


def test_stem_collision_ignores_case() -> None:
    # No files needed, so this also runs on case-insensitive filesystems.
    with pytest.raises(pipeline_export.StemCollisionError):
        pipeline_export.check_stems([Path("IMG_1.dng"), Path("img_1.NEF")])
    pipeline_export.check_stems([Path("IMG_1.dng"), Path("IMG_2.dng")])


def test_run_creates_config_export_does_not(tmp_path: Path) -> None:
    project = _project(tmp_path, config=False)
    assert runner.invoke(app, ["export", str(project)]).exit_code == 0
    assert not (project / "picturesq.yaml").exists()
    assert runner.invoke(app, ["run", str(project)]).exit_code == 0
    assert (project / "picturesq.yaml").exists()


def test_human_output_has_line_per_photo_and_summary(tmp_path: Path) -> None:
    project = _project(tmp_path)
    result = runner.invoke(app, ["run", str(project)])
    lines = result.stdout.strip().splitlines()
    assert lines[0].startswith("a.dng: web, archive")
    assert lines[1].startswith("b.dng:")
    assert lines[-1].startswith("2 photo(s), 0 failed")
