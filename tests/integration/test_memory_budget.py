"""The photo peak model holds on real originals (``pytest -m slow``).

Each export runs in a fresh Python process, so the measured peak is exactly what a worker
would use: the process's high-water mark of resident memory, read when it exits.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from picturesq.pipeline.budget import photo_peak_bytes

pytestmark = pytest.mark.slow

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REFERENCE_RAW = _REPO_ROOT / "reference" / "raw"

# Runs in the child: export one original with the default config, report peak and pixels.
_CHILD = """
import json, resource, sys, time
from pathlib import Path
from PIL import Image
from picturesq.config import ProjectConfig
from picturesq.pipeline.export import export_originals

original, exports = Path(sys.argv[1]), Path(sys.argv[2])
started = time.perf_counter()
result = export_originals([original], ProjectConfig(), exports)
seconds = time.perf_counter() - started
photo = result.photos[0]
if photo.error:
    sys.exit(photo.error)
with Image.open(photo.outputs["archive"]) as archive:  # full resolution
    width, height = archive.size
peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
peak *= 1 if sys.platform == "darwin" else 1024  # bytes on macOS, KiB on Linux
print(json.dumps({"peak": peak, "pixels": width * height, "seconds": seconds}))
"""


def _measure(original: Path, exports: Path) -> dict[str, float]:
    if sys.platform == "win32":
        pytest.skip("peak resident memory is read with `resource`, which Windows lacks")
    completed = subprocess.run(
        [sys.executable, "-c", _CHILD, str(original), str(exports)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout.strip().splitlines()[-1])


def _check(original: Path, exports: Path) -> None:
    measured = _measure(original, exports)
    peak, pixels = int(measured["peak"]), int(measured["pixels"])
    budget = photo_peak_bytes(pixels)
    print(
        f"{original.name}: {pixels / 1e6:.1f} MP, peak {peak / 2**20:.0f} MiB "
        f"(model {budget / 2**20:.0f} MiB), {measured['seconds']:.1f} s"
    )
    assert peak <= budget, (
        f"{original.name} peaked at {peak / 2**20:.0f} MiB, over the photo peak model "
        f"({budget / 2**20:.0f} MiB): the export holds more full-resolution arrays than before"
    )


@pytest.mark.integration
def test_sample_export_fits_the_photo_peak(samples_dir: Path, tmp_path: Path) -> None:
    original = samples_dir / "dji-fc4382.dng"
    if not original.exists():
        pytest.skip(f"{original.name} not found in {samples_dir}")
    _check(original, tmp_path)


@pytest.mark.reference
def test_reference_export_fits_the_photo_peak(tmp_path: Path) -> None:
    """The largest original in the private reference set (a 33 MP Pocket 4 DNG)."""
    originals = sorted(_REFERENCE_RAW.glob("*.DNG"), key=lambda path: path.stat().st_size)
    if not originals:
        pytest.skip(f"no reference originals in {_REFERENCE_RAW}")
    _check(originals[-1], tmp_path)
