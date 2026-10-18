"""Exposure: one global gain per photo, in scene-linear.

``exposure_ev = offset_ev + clamp(correction * (target_ev - median_ev), ±max_correction_ev)``

``offset_ev`` is how much brighter cameras render than the raw's own exposure: fitted to the
camera JPEGs of the CC0 samples and the reference set (ADR-0010), where the camera's
brightening was nearly constant (+2.3 ± 0.6 EV) and did not depend on the scene's median.
``correction`` pulls each photo's median toward ``target_ev`` for batch consistency; it is
off by default because cameras don't do it. ``target_ev`` is measured before ``offset_ev``, so
with ``correction`` 1 the median ends at ``offset_ev + target_ev``.
"""

from dataclasses import dataclass
from functools import partial

import numpy as np

from picturesq import parallel
from picturesq.colour.spaces import REC2020_TO_XYZ
from picturesq.colour.transfer import EV_FLOOR, MIDDLE_GREY, FloatArray
from picturesq.config import ExposureConfig

SAMPLE_PIXELS = 100_000
"""Luminance statistics use about this many pixels (a regular grid), whatever the size."""


def sample_grid(image: FloatArray) -> FloatArray:
    """A regular grid of about :data:`SAMPLE_PIXELS` pixels of ``image`` (a view, no copy)."""
    height, width = image.shape[:2]
    step = max(1, int(np.sqrt(height * width / SAMPLE_PIXELS)))
    return image[::step, ::step]


def luminance(image: FloatArray) -> FloatArray:
    """Relative luminance (CIE Y) of ``image`` (linear Rec.2020), one value per pixel."""
    return image @ REC2020_TO_XYZ[1].astype(np.float32)


def linear_to_ev(value: float) -> float:
    """A scene-linear value in EV relative to mid grey, clamped at :data:`EV_FLOOR`."""
    return float(np.log2(max(value, EV_FLOOR) / MIDDLE_GREY))


def median_ev(image: FloatArray) -> float:
    """Median luminance of ``image`` (linear Rec.2020) in EV relative to mid grey."""
    return linear_to_ev(float(np.median(luminance(sample_grid(image)))))


@dataclass(frozen=True)
class ExposureDecision:
    """How normalise chose a photo's exposure change."""

    ev: float
    """The exposure change, in EV: ``offset_ev`` plus the (limited) correction."""
    correction_ev: float
    """The correction part of ``ev``, after limiting; 0 when correction is off."""
    clamped: bool
    """The correction wanted more than ``max_correction_ev`` and was limited to it."""


def exposure_decision(image: FloatArray, config: ExposureConfig) -> ExposureDecision:
    """The exposure change for ``image`` and how it was reached."""
    if config.correction <= 0.0:
        return ExposureDecision(ev=config.offset_ev, correction_ev=0.0, clamped=False)
    wanted = config.correction * (config.target_ev - median_ev(image))
    limit = config.max_correction_ev
    correction = float(np.clip(wanted, -limit, limit))
    return ExposureDecision(
        ev=config.offset_ev + correction, correction_ev=correction, clamped=abs(wanted) > limit
    )


def exposure_ev(image: FloatArray, config: ExposureConfig) -> float:
    """The exposure change for ``image``, in EV."""
    return exposure_decision(image, config).ev


def apply_exposure(image: FloatArray, ev: float, out: FloatArray | None = None) -> FloatArray:
    """Multiply ``image`` by ``2**ev``. ``out`` may be ``image``."""
    out = np.empty_like(image) if out is None else out
    gain = np.float32(2.0**ev)
    if not (image.flags.c_contiguous and out.flags.c_contiguous):
        return np.multiply(image, gain, out=out)
    source, target = image.reshape(-1), out.reshape(-1)
    parallel.run(
        partial(np.multiply, source[block], gain, out=target[block])
        for block in parallel.pixel_blocks(len(source))
    )
    return out
