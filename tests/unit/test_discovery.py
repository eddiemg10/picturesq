"""Tests for original discovery."""

from pathlib import Path

import pytest

from picturesq.decode import find_originals


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


def _names(project: Path) -> list[str]:
    return [p.name for p in find_originals(project)]


def test_extension_match_is_case_insensitive(tmp_path: Path) -> None:
    for name in ("a.DNG", "b.dng", "c.Nef"):
        _touch(tmp_path / name)
    assert _names(tmp_path) == ["a.DNG", "b.dng", "c.Nef"]


def test_ignores_non_originals(tmp_path: Path) -> None:
    _touch(tmp_path / "keep.dng")
    _touch(tmp_path / "x.jpg")
    _touch(tmp_path / "picturesq.yaml")
    _touch(tmp_path / ".hidden.dng")
    _touch(tmp_path / "sub" / "y.dng")
    _touch(tmp_path / "exports" / "x.dng")
    _touch(tmp_path / ".picturesq" / "x.dng")
    (tmp_path / "folder.dng").mkdir()
    assert _names(tmp_path) == ["keep.dng"]


def test_sorted_by_casefolded_name(tmp_path: Path) -> None:
    for name in ("b.dng", "A.dng", "a.dng", "C.dng", "img_10.dng", "img_2.dng"):
        _touch(tmp_path / name)
    assert _names(tmp_path) == ["A.dng", "a.dng", "b.dng", "C.dng", "img_10.dng", "img_2.dng"]


def test_symlink_to_file_counts(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere" / "real.dng"
    _touch(target)
    project = tmp_path / "project"
    project.mkdir()
    try:
        (project / "link.dng").symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported here")
    assert _names(project) == ["link.dng"]


def test_missing_folder_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        find_originals(tmp_path / "nope")


def test_file_instead_of_folder_raises(tmp_path: Path) -> None:
    f = tmp_path / "a.dng"
    _touch(f)
    with pytest.raises(NotADirectoryError):
        find_originals(f)
