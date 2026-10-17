"""Memory model of an export: the photo peak, used to size the worker pool.

The **photo peak** is the most memory one process uses at once to export one photo with
every default output: the interpreter and libraries plus the full-resolution arrays the
stages and outputs hold at the same time. It grows with the photo's pixel count, so it is
modelled as a fixed overhead plus a cost per pixel.

The constants are measured, not guessed: ``tests/integration/test_memory_budget.py`` exports
real originals in a fresh process and fails if the measured peak exceeds this model. Lower
them when a change makes the pipeline leaner; a change that needs them raised has added a
full-resolution array (12 bytes per pixel) and should say why.

Measured on Linux, default config, ``web`` + ``archive`` outputs (2026-10-17):

- DJI FC4382 sample, 12.1 MP: 737 MiB in 33 s
- Pocket 4, 33.2 MP: 1776 MiB in 63 s

That is ~52 bytes per pixel (about four float32 RGB images) over ~140 MiB of overhead; the
constants below leave ~10 % headroom, less than one extra full-resolution array.
"""

from typing import Final

PROCESS_OVERHEAD_BYTES: Final = 256 * 2**20
"""Python, numpy, rawpy and friends, plus what doesn't scale with the photo."""
PEAK_BYTES_PER_PIXEL: Final = 56
"""Full-resolution arrays alive at the peak (a float32 RGB image is 12 bytes per pixel)."""


def photo_peak_bytes(pixels: int) -> int:
    """Upper bound on one process's memory while it exports a photo of ``pixels`` pixels."""
    return PROCESS_OVERHEAD_BYTES + PEAK_BYTES_PER_PIXEL * pixels
