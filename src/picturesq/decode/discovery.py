"""Original discovery: list the RAW originals in a project folder."""

from __future__ import annotations

from pathlib import Path

# Curated by hand: rawpy does not expose LibRaw's list of supported extensions.
RAW_EXTENSIONS: frozenset[str] = frozenset(
    {
        "dng", "cr2", "cr3", "crw", "nef", "nrw", "arw", "srf", "sr2", "raf",
        "orf", "rw2", "raw", "rwl", "pef", "ptx", "srw", "x3f", "3fr", "fff",
        "iiq", "mos", "mef", "mrw", "erf", "kdc", "dcr", "k25", "gpr",
    }
)  # fmt: skip

# Generated-output folders; never searched for originals.
_IGNORED_DIRS = frozenset({".picturesq", "exports"})


def find_originals(project: Path) -> list[Path]:
    """Return the RAW originals directly inside ``project``, sorted by filename.

    Top level only: a project is a folder of RAWs, so subfolders are never
    searched (this also excludes ``.picturesq/`` and ``exports/``). Extensions
    match case-insensitively, hidden files (names starting with ``.``) and
    non-files are skipped, and symlinks to files count as originals. The order
    is case-folded name then name, so it is identical on every platform.

    Raises:
        FileNotFoundError: ``project`` does not exist.
        NotADirectoryError: ``project`` is not a directory.
    """
    if not project.exists():
        raise FileNotFoundError(f"project folder not found: {project}")
    if not project.is_dir():
        raise NotADirectoryError(f"project is not a folder: {project}")
    found = [
        p
        for p in project.iterdir()
        if p.name not in _IGNORED_DIRS
        and not p.name.startswith(".")
        and p.suffix[1:].lower() in RAW_EXTENSIONS
        and p.is_file()
    ]
    return sorted(found, key=lambda p: (p.name.casefold(), p.name))
