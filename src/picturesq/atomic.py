"""Atomic file writes: every file picturesq writes goes through here (ADR-0004)."""

import os
import tempfile
from pathlib import Path


def _umask() -> int:
    """The process umask (reading it means setting it, so set it straight back)."""
    mask = os.umask(0)
    os.umask(mask)
    return mask


def atomic_write(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` via a temp file in the same folder, then rename over it.

    A crash mid-write leaves the old file (or none) intact, never a truncated one, and a
    watcher (the UI) never reads a half-written file. Parent folders are created. The file
    gets the usual permissions for a new file (0666 minus the umask), not the temp file's 0600.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as file:
            if os.name == "posix":
                os.fchmod(fd, 0o666 & ~_umask())
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
