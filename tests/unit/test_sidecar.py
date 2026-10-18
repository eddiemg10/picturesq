"""The export sidecar: what it records, and that it is reproducible."""

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from typer.testing import CliRunner

from picturesq import __version__
from picturesq.cli import app
from picturesq.config import ProjectConfig
from picturesq.decode import DecodeError, PhotoInfo
from picturesq.export import sha256_file, sidecar_document, sidecar_path
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
    ramp = np.linspace(0.0, 0.8, 120, dtype=np.float32)
    image = np.empty((80, 120, 3), dtype=np.float32)
    image[...] = ramp[None, :, None]
    return image


@pytest.fixture(autouse=True)
def fake_decode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline_export, "decode_original", _synthetic)


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / "a.dng").write_bytes(b"not really a raw")
    (project / "picturesq.yaml").write_text(CONFIG)
    return project


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_sidecar_path() -> None:
    assert sidecar_path(Path("exports/web/IMG_1.jpg")) == Path("exports/web/IMG_1.picturesq.json")


def test_sha256_file_matches_hashlib(tmp_path: Path) -> None:
    path = tmp_path / "f"
    data = np.random.default_rng(0).bytes(3 << 20)  # spans several chunks
    path.write_bytes(data)
    assert sha256_file(path) == hashlib.sha256(data).hexdigest()


def test_document_records_version_original_output_and_config() -> None:
    config = ProjectConfig()
    document = sidecar_document(
        version="1.2.3",
        original=Path("x/IMG.dng"),
        original_sha256="ab",
        output="web",
        config=config,
    )
    assert document["picturesq_version"] == "1.2.3"
    assert document["original"] == {"name": "IMG.dng", "sha256": "ab"}
    assert document["output"] == {"name": "web", **config.export.outputs["web"].model_dump()}
    assert set(document["config"]) == {"version", "decode", "normalise", "grade", "photos"}
    # The recorded config is a valid config: it reproduces the render.
    ProjectConfig.model_validate(document["config"])


def test_run_writes_a_sidecar_per_output(tmp_path: Path) -> None:
    project = _project(tmp_path)
    assert runner.invoke(app, ["run", str(project)]).exit_code == 0
    web = _read(project / "exports" / "web" / "a.picturesq.json")
    archive = _read(project / "exports" / "archive" / "a.picturesq.json")
    assert web["picturesq_version"] == __version__
    assert web["original"] == {"name": "a.dng", "sha256": sha256_file(project / "a.dng")}
    assert web["output"]["name"] == "web"
    assert archive["output"]["long_edge"] is None
    assert web["config"] == archive["config"]


def test_export_is_reproducible(tmp_path: Path) -> None:
    project = _project(tmp_path)
    first, second = tmp_path / "first", tmp_path / "second"
    for out in (first, second):
        assert runner.invoke(app, ["export", str(project), "--out", str(out)]).exit_code == 0
    files = sorted(p.relative_to(first) for p in first.rglob("*") if p.is_file())
    assert {p.suffix for p in files} == {".jpg", ".json"}
    for relative in files:
        assert (first / relative).read_bytes() == (second / relative).read_bytes(), relative


def test_config_change_changes_the_sidecar(tmp_path: Path) -> None:
    project = _project(tmp_path)
    sidecar = project / "exports" / "web" / "a.picturesq.json"
    assert runner.invoke(app, ["run", str(project)]).exit_code == 0
    before = _read(sidecar)
    (project / "picturesq.yaml").write_text(CONFIG + "decode: {demosaic: vng}\n")
    assert runner.invoke(app, ["run", str(project)]).exit_code == 0
    after = _read(sidecar)
    assert before["config"]["decode"]["demosaic"] == "ahd"
    assert after["config"]["decode"]["demosaic"] == "vng"


def test_document_records_only_this_photos_overrides() -> None:
    config = ProjectConfig.model_validate(
        {
            "photos": {
                "IMG.DNG": {"normalise": {"wb_kelvin": 3200.0, "enabled": True}},
                "other.dng": {"normalise": {"exposure_ev": 1.0}},
            }
        }
    )

    def document(name: str) -> dict[str, Any]:
        return sidecar_document(
            version="1", original=Path(name), original_sha256="ab", output="web", config=config
        )

    with_overrides = document("img.dng")["config"]
    assert with_overrides["photos"] == {
        "img.dng": {
            "normalise": {"enabled": True, "exposure_ev": None, "wb_kelvin": 3200.0, "tint": None}
        }
    }
    # The recorded config resolves this photo's overrides the same way.
    recorded = ProjectConfig.model_validate(with_overrides)
    assert recorded.photo("img.dng") == config.photo("img.dng")
    assert document("plain.dng")["config"]["photos"] == {}
    assert document("plain.dng")["sidecar_version"] == 2


def test_run_records_overrides_and_reads_photo_info_only_when_needed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    read: list[str] = []

    def fake_info(path: Path, _config: object) -> PhotoInfo:
        read.append(path.name)
        return PhotoInfo((0.3457, 0.3585), 5000.0, 0.0, 0.0, 1.0)

    monkeypatch.setattr(pipeline_export, "read_photo_info", fake_info)
    project = _project(tmp_path)
    (project / "b.dng").write_bytes(b"another")
    overrides = "photos:\n  a.dng:\n    normalise: {wb_kelvin: 3000, exposure_ev: 1.5}\n"
    (project / "picturesq.yaml").write_text(CONFIG + overrides)
    assert runner.invoke(app, ["--workers", "1", "run", str(project)]).exit_code == 0
    assert read == ["a.dng"]
    a = _read(project / "exports" / "web" / "a.picturesq.json")
    b = _read(project / "exports" / "web" / "b.picturesq.json")
    assert a["config"]["photos"]["a.dng"]["normalise"]["wb_kelvin"] == 3000.0
    assert b["config"]["photos"] == {}


def test_white_balance_override_without_an_as_shot_white_fails_that_photo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        pipeline_export, "read_photo_info", lambda *_: PhotoInfo(None, None, None, 0.0, 1.0)
    )
    project = _project(tmp_path)
    (project / "picturesq.yaml").write_text(CONFIG + "photos: {a.dng: {normalise: {tint: 5}}}\n")
    result = runner.invoke(app, ["run", str(project)])
    assert result.exit_code == 1
    assert "as-shot" in result.output
    assert not list(project.rglob("*.picturesq.json"))


def test_failed_photo_writes_no_sidecar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_a: object, **_k: object) -> np.ndarray:
        raise DecodeError("corrupt")

    monkeypatch.setattr(pipeline_export, "decode_original", broken)
    project = _project(tmp_path)
    assert runner.invoke(app, ["run", str(project)]).exit_code == 1
    assert not list(project.rglob("*.picturesq.json"))
