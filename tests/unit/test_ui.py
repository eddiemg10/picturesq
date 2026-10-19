"""The UI's session and web app without decoding: edits, the YAML they write, the API."""

from pathlib import Path

import pytest
import yaml
from starlette.testclient import TestClient

from picturesq.config import CONFIG_FILENAME, load_project_config
from picturesq.ui.app import create_app
from picturesq.ui.session import EditError, Session

NAMES = ("A.DNG", "B.DNG", "C.DNG")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    for name in NAMES:
        (tmp_path / name).write_bytes(b"not a real raw")
    return tmp_path


def _saved(project: Path) -> dict:
    return yaml.safe_load((project / CONFIG_FILENAME).read_text(encoding="utf-8"))


def test_opening_lists_photos_and_writes_nothing(project: Path) -> None:
    session = Session.open(project)
    assert session.names == list(NAMES)
    assert not (project / CONFIG_FILENAME).exists()
    assert session.state()["config_exists"] is False


def test_project_look_and_adjustments(project: Path) -> None:
    session = Session.open(project)
    session.edit({"target": "project", "look": {"name": "cold/nordic", "intensity": 0.5}})
    session.edit({"target": "project", "adjustments": {"warmth": 10}})
    config = load_project_config(project / CONFIG_FILENAME)
    assert config.grade.look is not None
    assert (config.grade.look.name, config.grade.look.intensity) == ("cold/nordic", 0.5)
    assert config.grade.adjustments.warmth == 10
    session.edit({"target": "project", "look": {"name": None}})
    assert load_project_config(project / CONFIG_FILENAME).grade.look is None


def test_photo_overrides_only_say_what_they_override(project: Path) -> None:
    session = Session.open(project)
    session.edit(
        {
            "target": ["A.DNG", "B.DNG"],
            "look": {"name": "bw/silver", "intensity": 1.0},
            "adjustments": {"exposure": 0.5},
            "normalise": {"exposure_ev": 2.5},
        }
    )
    photos = _saved(project)["photos"]
    assert set(photos) == {"A.DNG", "B.DNG"}
    assert photos["A.DNG"] == {
        "normalise": {"exposure_ev": 2.5},
        "grade": {
            "look": {"name": "bw/silver", "intensity": 1.0},
            "adjustments": {"exposure": 0.5},
        },
    }


def test_removing_every_override_drops_the_photo(project: Path) -> None:
    session = Session.open(project)
    session.edit({"target": ["A.DNG"], "adjustments": {"tint": 5}, "normalise": {"tint": 3}})
    session.edit({"target": ["A.DNG"], "adjustments": {"tint": None}, "normalise": {"tint": None}})
    assert _saved(project)["photos"] == {}
    session.edit({"target": ["B.DNG"], "look": {"name": "warm/terracotta"}})
    session.edit({"target": ["B.DNG"], "reset": True})
    assert _saved(project)["photos"] == {}


def test_no_look_for_a_photo_is_intensity_zero_of_the_project_look(project: Path) -> None:
    session = Session.open(project)
    session.edit({"target": "project", "look": {"name": "cold/steel"}})
    session.edit({"target": ["C.DNG"], "look": {"name": None}})
    config = load_project_config(project / CONFIG_FILENAME)
    assert config.photo_look("C.DNG") is None
    assert config.photo_look("A.DNG") is not None
    session.edit({"target": ["C.DNG"], "look": None})  # follow the project again
    assert load_project_config(project / CONFIG_FILENAME).photo_look("C.DNG") is not None


@pytest.mark.parametrize(
    "change",
    [
        {"target": "project", "look": {"name": "cold/missing"}},
        {"target": ["A.DNG"], "adjustments": {"exposure": 99}},
        {"target": ["A.DNG"], "look": {"name": "bw/silver", "parameters": {"nope": 1}}},
        {"target": ["Z.DNG"], "adjustments": {"exposure": 1}},
        {"target": "everything"},
    ],
)
def test_invalid_edits_save_nothing(project: Path, change: dict) -> None:
    session = Session.open(project)
    with pytest.raises(EditError):
        session.edit(change)
    assert not (project / CONFIG_FILENAME).exists()


def test_an_edit_from_outside_is_picked_up(project: Path) -> None:
    session = Session.open(project)
    session.edit({"target": "project", "adjustments": {"contrast": 0.1}})
    revision = session.revision
    path = project / CONFIG_FILENAME
    text = path.read_text(encoding="utf-8").replace("contrast: 0.1", "contrast: 0.2")
    path.write_text(text, encoding="utf-8")
    import os

    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert session.reload()
    assert session.revision > revision
    assert session.config.grade.adjustments.contrast == 0.2


def test_api_state_edit_and_config(project: Path) -> None:
    client = TestClient(create_app(Session.open(project)))
    state = client.get("/api/state").json()
    assert [photo["name"] for photo in state["photos"]] == list(NAMES)
    assert {look["key"] for look in state["looks"]} >= {"bw/silver", "cinematic/teal_orange"}
    response = client.post(
        "/api/edit", json={"target": ["B.DNG"], "look": {"name": "warm/golden_hour"}}
    )
    assert response.status_code == 200
    photo = next(p for p in response.json()["photos"] if p["name"] == "B.DNG")
    assert photo["look"]["name"] == "warm/golden_hour" and photo["look_override"]
    assert "warm/golden_hour" in client.get("/api/config").text
    bad = client.post("/api/edit", json={"target": ["B.DNG"], "adjustments": {"warmth": 500}})
    assert bad.status_code == 400 and "warmth" in bad.json()["error"]
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_api_preview_rejects_bad_requests(project: Path) -> None:
    client = TestClient(create_app(Session.open(project)))
    assert client.get("/api/preview/NOPE.DNG").status_code == 404
    assert client.get("/api/preview/A.DNG?size=huge").status_code == 400
    assert client.get("/api/preview/A.DNG?variant=look:cold/missing").status_code == 400
