"""The proxy cache and `picturesq decode`, with decode replaced by a synthetic image."""

import json
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from picturesq.cli import app
from picturesq.config import DecodeConfig
from picturesq.decode import DecodeError
from picturesq.pipeline import proxy as proxy_module
from picturesq.pipeline.proxy import CACHE_DIRNAME, load_proxy, proxy_key

runner = CliRunner()
SMALL = DecodeConfig(proxy_long_edge=256)
"""Keeps the resize fast; the CLI tests use the default (2048: no resize of 600x400)."""


class FakeDecode:
    """Counts calls; returns a 600x400 ramp (what a half-size decode might give)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def __call__(self, path: Path, config: DecodeConfig, *, half_size: bool = False) -> np.ndarray:
        self.calls.append((path.name, half_size))
        ramp = np.linspace(0.0, 4.0, 600, dtype=np.float32)
        image = np.empty((400, 600, 3), dtype=np.float32)
        image[...] = ramp[None, :, None]
        image[..., 2] *= 0.5
        return image


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeDecode:
    decode = FakeDecode()
    monkeypatch.setattr(proxy_module, "decode_original", decode)
    return decode


def _original(tmp_path: Path, name: str = "a.dng", data: bytes = b"raw bytes") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _cache_files(cache: Path) -> list[str]:
    return sorted(p.name for p in (cache / "proxies").iterdir())


def test_builds_a_half_size_float16_proxy_at_the_long_edge(
    tmp_path: Path, fake: FakeDecode
) -> None:
    proxy = load_proxy(_original(tmp_path), SMALL, tmp_path / "cache")
    assert fake.calls == [("a.dng", True)]
    assert not proxy.cached
    assert proxy.image.dtype == np.float32
    assert proxy.image.shape == (171, 256, 3)
    on_disk = np.load(proxy.path)
    assert on_disk.dtype == np.float16
    # Values above 1 (scene-linear headroom) survive float16.
    assert 3.9 < float(on_disk[..., 0].max()) <= 4.0


def test_second_load_is_a_cache_hit(tmp_path: Path, fake: FakeDecode) -> None:
    original, cache = _original(tmp_path), tmp_path / "cache"
    first = load_proxy(original, SMALL, cache)
    second = load_proxy(original, SMALL, cache)
    assert len(fake.calls) == 1
    assert second.cached
    np.testing.assert_array_equal(first.image, second.image)


@pytest.mark.parametrize(
    "change",
    ["decode_config", "original_bytes", "version"],
)
def test_a_change_invalidates_and_removes_the_stale_proxy(
    tmp_path: Path, fake: FakeDecode, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    original, cache = _original(tmp_path), tmp_path / "cache"
    config = SMALL
    first = load_proxy(original, config, cache)
    if change == "decode_config":
        config = DecodeConfig(proxy_long_edge=256, demosaic="vng")
    elif change == "original_bytes":
        original.write_bytes(b"other raw bytes")
    else:
        monkeypatch.setattr(
            proxy_module, "proxy_key", lambda sha, decode: proxy_key(sha, decode, version="9")
        )
    second = load_proxy(original, config, cache)
    assert not second.cached
    assert len(fake.calls) == 2
    assert second.path != first.path
    assert _cache_files(cache) == [second.path.name]


def test_proxy_long_edge_is_respected_and_never_upscales(tmp_path: Path, fake: FakeDecode) -> None:
    cache = tmp_path / "cache"
    small = load_proxy(_original(tmp_path), DecodeConfig(proxy_long_edge=300), cache)
    assert small.image.shape[:2] == (200, 300)
    large = load_proxy(_original(tmp_path), DecodeConfig(proxy_long_edge=8192), cache)
    assert large.image.shape[:2] == (400, 600)


def test_corrupt_cache_file_is_rebuilt(tmp_path: Path, fake: FakeDecode) -> None:
    original, cache = _original(tmp_path), tmp_path / "cache"
    first = load_proxy(original, SMALL, cache)
    first.path.write_bytes(b"truncated")
    second = load_proxy(original, SMALL, cache)
    assert not second.cached
    assert np.load(second.path).dtype == np.float16


def test_other_photos_proxies_are_kept(tmp_path: Path, fake: FakeDecode) -> None:
    cache = tmp_path / "cache"
    a = load_proxy(_original(tmp_path, "a.dng"), SMALL, cache)
    # "a.b" shares the prefix "a." with a's proxy files: must not be mistaken for a's.
    ab = load_proxy(_original(tmp_path, "a.b.dng"), SMALL, cache)
    load_proxy(
        _original(tmp_path, "a.dng"), DecodeConfig(proxy_long_edge=256, demosaic="vng"), cache
    )
    names = _cache_files(cache)
    assert ab.path.name in names
    assert a.path.name not in names
    assert len(names) == 2


# --- `picturesq decode` ---------------------------------------------------------------------


def _project(tmp_path: Path, names: tuple[str, ...] = ("a.dng", "b.dng")) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    for name in names:
        (project / name).write_bytes(b"raw " + name.encode())
    return project


def test_decode_command_builds_then_reuses(tmp_path: Path, fake: FakeDecode) -> None:
    project = _project(tmp_path)
    first = runner.invoke(app, ["decode", str(project), "--json"])
    assert first.exit_code == 0, first.output
    document = json.loads(first.stdout)
    assert document["summary"] == {
        "photos": 2,
        "built": 2,
        "cached": 0,
        "failed": 0,
        "seconds": document["summary"]["seconds"],
    }
    assert Path(document["photos"][0]["proxy"]).parent == project / CACHE_DIRNAME / "proxies"
    second = json.loads(runner.invoke(app, ["decode", str(project), "--json"]).stdout)
    assert [p["cached"] for p in second["photos"]] == [True, True]
    assert len(fake.calls) == 2
    assert not (project / "picturesq.yaml").exists()


def test_decode_command_config_change_rebuilds(tmp_path: Path, fake: FakeDecode) -> None:
    project = _project(tmp_path, ("a.dng",))
    assert runner.invoke(app, ["decode", str(project)]).exit_code == 0
    (project / "picturesq.yaml").write_text("decode: {highlight_mode: clip}\n")
    result = runner.invoke(app, ["decode", str(project)])
    assert result.exit_code == 0
    assert "a.dng: built" in result.output
    assert "1 photo(s): 1 built, 0 cached, 0 failed" in result.output


def test_decode_command_reports_failures(
    tmp_path: Path, fake: FakeDecode, monkeypatch: pytest.MonkeyPatch
) -> None:
    def flaky(path: Path, config: DecodeConfig, *, half_size: bool = False) -> np.ndarray:
        if path.name == "a.dng":
            raise DecodeError("cannot decode a.dng: corrupt")
        return fake(path, config, half_size=half_size)

    monkeypatch.setattr(proxy_module, "decode_original", flaky)
    project = _project(tmp_path)
    result = runner.invoke(app, ["decode", str(project), "--json"])
    assert result.exit_code == 1
    document = json.loads(result.stdout)
    assert "corrupt" in document["photos"][0]["error"]
    assert document["photos"][0]["proxy"] is None
    assert document["photos"][1]["error"] is None


def test_decode_command_invalid_config_exits_2(tmp_path: Path, fake: FakeDecode) -> None:
    project = _project(tmp_path)
    (project / "picturesq.yaml").write_text("decode: {proxy_long_edge: 10}\n")
    assert runner.invoke(app, ["decode", str(project)]).exit_code == 2


def test_decode_command_stem_collision_exits_1(tmp_path: Path, fake: FakeDecode) -> None:
    project = _project(tmp_path, ("a.dng", "a.arw"))
    result = runner.invoke(app, ["decode", str(project)])
    assert result.exit_code == 1
    assert fake.calls == []
