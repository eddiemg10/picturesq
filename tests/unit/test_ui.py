"""The UI's session and web app without decoding: edits, the YAML they write, the API."""

from pathlib import Path

import pytest
import yaml
from PIL.ExifTags import Base
from starlette.testclient import TestClient

from picturesq.config import CONFIG_FILENAME, load_project_config
from picturesq.decode import CaptureExif
from picturesq.ui import session as session_module
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


def test_state_says_which_photos_have_been_analysed(project: Path) -> None:
    session = Session.open(project)
    state = session.state()
    revision = state["revision"]
    assert state["analysed"] == 0
    assert not any(photo["analysed"] for photo in state["photos"])
    session.warm()  # these aren't real RAWs: every photo fails, which is analysed too
    state = session.state()
    assert state["analysed"] == len(NAMES)
    assert all(photo["analysed"] and photo["error"] for photo in state["photos"])
    assert state["revision"] == revision  # analysing changes no preview


# --- date and time ------------------------------------------------------------------------

CAMERA_TIMES = {"A.DNG": "2000:07:07 10:00:00", "B.DNG": "2000:07:07 11:30:00"}
"""C.DNG records no time, like a camera that never wrote one."""


@pytest.fixture
def timed(project: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    def read(path: Path) -> CaptureExif:
        when = CAMERA_TIMES.get(path.name)
        return CaptureExif(exif={} if when is None else {Base.DateTimeOriginal: when})

    monkeypatch.setattr(session_module, "read_capture_exif", read)
    return project


def _capture(session: Session, name: str) -> dict:
    return next(p for p in session.state()["photos"] if p["name"] == name)["capture"]


def test_state_reports_camera_and_corrected_times(timed: Path) -> None:
    session = Session.open(timed)
    assert _capture(session, "A.DNG") == {
        "camera": "2000-07-07T10:00:00",
        "corrected": "2000-07-07T10:00:00",
        "how": "unchanged",
        "own": False,
    }
    assert _capture(session, "C.DNG")["how"] == "no time recorded"
    assert session.state()["metadata"] == {"time_shift": "+0d 00:00:00", "time_zone": None}


def test_shift_from_one_photo_moves_every_photo(timed: Path) -> None:
    session = Session.open(timed)
    reference = {"photo": "A.DNG", "actual": "2026-10-17T20:05"}
    session.edit({"target": "project", "metadata": {"reference": reference}})
    assert _saved(timed)["metadata"]["time_shift"] == "+9598d 10:05:00"
    assert _capture(session, "A.DNG")["corrected"] == "2026-10-17T20:05:00"
    assert _capture(session, "B.DNG") == {
        "camera": "2000-07-07T11:30:00",
        "corrected": "2026-10-17T21:35:00",
        "how": "shifted",
        "own": False,
    }
    assert _capture(session, "C.DNG")["corrected"] is None  # nothing to shift


def test_time_shift_and_zone_directly(timed: Path) -> None:
    session = Session.open(timed)
    session.edit(
        {"target": "project", "metadata": {"time_shift": "-1d2h30m", "time_zone": "+01:00"}}
    )
    assert _saved(timed)["metadata"] == {"time_shift": "-1d 02:30:00", "time_zone": "+01:00"}
    session.edit({"target": "project", "metadata": {"time_shift": None, "time_zone": None}})
    assert _saved(timed)["metadata"] == {"time_shift": "+0d 00:00:00", "time_zone": None}


def test_photo_capture_time_survives_reset_until_cleared(timed: Path) -> None:
    session = Session.open(timed)
    session.edit(
        {
            "target": ["C.DNG"],
            "metadata": {"capture_time": "2026-10-18 09:30"},
            "adjustments": {"tint": 3},
        }
    )
    assert _saved(timed)["photos"]["C.DNG"]["metadata"] == {"capture_time": "2026-10-18T09:30:00"}
    assert _capture(session, "C.DNG")["how"] == "set for this photo"
    assert _capture(session, "C.DNG")["own"] is True
    session.edit({"target": ["C.DNG"], "reset": True})
    assert _saved(timed)["photos"] == {
        "C.DNG": {"metadata": {"capture_time": "2026-10-18T09:30:00"}}
    }
    session.edit({"target": ["C.DNG"], "metadata": {"capture_time": None}})
    assert _saved(timed)["photos"] == {}


@pytest.mark.parametrize(
    "metadata",
    [
        {"time_shift": "soon"},
        {"time_zone": "+25:00"},
        {"reference": {"photo": "C.DNG", "actual": "2026-10-17 20:05"}},  # no camera time
        {"reference": {"photo": "A.DNG", "actual": "yesterday"}},
        {"reference": {"photo": "Z.DNG", "actual": "2026-10-17 20:05"}},
    ],
)
def test_invalid_project_metadata_edits_save_nothing(timed: Path, metadata: dict) -> None:
    session = Session.open(timed)
    with pytest.raises(EditError):
        session.edit({"target": "project", "metadata": metadata})
    assert not (timed / CONFIG_FILENAME).exists()


def test_a_capture_time_with_a_zone_is_refused(timed: Path) -> None:
    session = Session.open(timed)
    with pytest.raises(EditError, match="without a zone"):
        session.edit({"target": ["A.DNG"], "metadata": {"capture_time": "2026-10-17T20:05+01:00"}})
    assert not (timed / CONFIG_FILENAME).exists()


def test_api_rewrites_export_dates(timed: Path) -> None:
    client = TestClient(create_app(Session.open(timed)))
    response = client.post("/api/metadata/apply", json={"outputs": ["web"]})
    assert response.json() == {"exports": 0, "rewritten": 0, "failed": []}
    assert client.post("/api/metadata/apply", json={"outputs": ["nope"]}).status_code == 400
