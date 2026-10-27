"""The UI's previews on a real CC0 sample: a JPEG of the base's size, and a look changes it."""

import io
import shutil
from pathlib import Path

import pytest
from PIL import Image
from starlette.testclient import TestClient

from picturesq.ui.app import create_app
from picturesq.ui.session import LONG_EDGES, Session

pytestmark = pytest.mark.integration

NAME = "dji-fc4382.dng"


def test_previews_render_and_follow_the_config(samples_dir: Path, tmp_path: Path) -> None:
    source = samples_dir / NAME
    if not source.is_file():
        pytest.skip(f"{NAME} not found in {samples_dir}")
    shutil.copy(source, tmp_path / NAME)
    client = TestClient(create_app(Session.open(tmp_path)))

    def preview(size: str, variant: str = "current") -> bytes:
        response = client.get(f"/api/preview/{NAME}?size={size}&variant={variant}")
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "image/jpeg"
        return response.content

    for size, edge in LONG_EDGES.items():
        assert max(Image.open(io.BytesIO(preview(size))).size) == edge
    neutral = preview("thumb")
    assert preview("thumb", "neutral") == neutral  # no look, no adjustments yet
    assert preview("thumb", "look:bw/silver") != neutral
    client.post("/api/edit", json={"target": [NAME], "look": {"name": "bw/silver"}})
    assert preview("thumb") == preview("thumb", "look:bw/silver")
    state = client.get("/api/state").json()["photos"][0]
    assert state["exposure_ev"] is not None and state["error"] is None
