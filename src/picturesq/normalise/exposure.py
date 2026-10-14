"""Exposure: one global gain per photo, in scene-linear.

``exposure_ev = offset_ev + clamp(correction * (target_ev - median_ev), ±max_correction_ev)``

``offset_ev`` is how much brighter cameras render than the raw's own exposure: fitted to the
camera JPEGs of the CC0 samples and the reference set (ADR-0010), where the camera's
brightening was nearly constant (+2.3 ± 0.6 EV) and did not depend on the scene's median.
``correction`` pulls each photo's median toward ``target_ev`` for batch consistency; it is
off by default because cameras don't do it.
"""

import numpy as np

from picturesq.colour.spaces import REC2020_TO_XYZ
from picturesq.colour.transfer import EV_FLOOR, MIDDLE_GREY, FloatArray
from picturesq.config import ExposureConfig

SAMPLE_PIXELS = 100_000
"""Luminance statistics use about this many pixels (a regular grid), whatever the size."""


def median_ev(image: FloatArray) -> float:
    """Median luminance of ``image`` (linear Rec.2020) in EV relative to mid grey."""
    height, width = image.shape[:2]
    step = max(1, int(np.sqrt(height * width / SAMPLE_PIXELS)))
    luminance = image[::step, ::step] @ REC2020_TO_XYZ[1].astype(np.float32)
    return float(np.log2(max(float(np.median(luminance)), EV_FLOOR) / MIDDLE_GREY))


def exposure_ev(image: FloatArray, config: ExposureConfig) -> float:
    """The exposure change for ``image``, in EV."""
    correction = 0.0
    if config.correction > 0.0:
        correction = config.correction * (config.target_ev - median_ev(image))
        correction = float(np.clip(correction, -config.max_correction_ev, config.max_correction_ev))
    return config.offset_ev + correction


def apply_exposure(image: FloatArray, ev: float, out: FloatArray | None = None) -> FloatArray:
    """Multiply ``image`` by ``2**ev``. ``out`` may be ``image``."""
    return np.multiply(image, np.float32(2.0**ev), out=out)
