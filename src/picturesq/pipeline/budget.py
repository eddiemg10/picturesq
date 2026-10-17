"""Memory model of an export: the photo peak, used to size the worker pool.

The **photo peak** is the most memory one process uses at once to export one photo with
every default output: the interpreter and libraries plus the full-resolution arrays the
stages and outputs hold at the same time. It grows with the photo's pixel count, so it is
modelled as a fixed overhead plus a cost per pixel.

The constants are measured, not guessed: ``tests/integration/test_memory_budget.py`` exports
real originals in a fresh process and fails if the measured peak exceeds this model. Lower
them when a change makes the pipeline leaner; a change that needs them raised has added a
full-resolution array (12 bytes per pixel) and should say why.

Measured on Linux, default config, ``web`` + ``archive`` outputs, 4 threads (2026-10-17,
after #69):

- DJI FC4382 sample, 12.1 MP: 589 MiB
- Pocket 4, 33.2 MP: 1031 MiB (was 1206 MiB before #69)

The peak is the ``web`` output's resize: the scene image plus one Pillow copy of each
channel, three resized at once (24 bytes per pixel), plus Pillow's half-resized
intermediates, which grow with the photo's height rather than its area (~220 MiB at
33 MP). The fixed part below covers those and the interpreter; with ~26 bytes per pixel
the model leaves ~10 % headroom at both sizes, less than one extra full-resolution array.
Per-thread temporaries are block-sized, so the thread count barely moves the peak (glibc's
per-thread memory pools would; see ``parallel.limit_allocator_arenas``); fewer threads
resize fewer channels at once, so the model is an upper bound for them too.
"""

from typing import Final

PROCESS_OVERHEAD_BYTES: Final = 352 * 2**20
"""Python, numpy, rawpy and friends, plus what doesn't scale with the photo's area."""
PEAK_BYTES_PER_PIXEL: Final = 26
"""Full-resolution arrays alive at the peak (a float32 RGB image is 12 bytes per pixel)."""


def photo_peak_bytes(pixels: int) -> int:
    """Upper bound on one process's memory while it exports a photo of ``pixels`` pixels."""
    return PROCESS_OVERHEAD_BYTES + PEAK_BYTES_PER_PIXEL * pixels
