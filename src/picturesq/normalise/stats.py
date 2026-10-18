"""Stats: a few per-photo measurements that flags, outliers and the review panel read.

All are measured on the same regular grid of about ``SAMPLE_PIXELS`` pixels as
:func:`~picturesq.normalise.exposure.median_ev`, so ``p50_ev`` equals the median it uses.
Luminance percentiles are taken in scene-linear and then expressed in EV relative to mid
grey (``log2`` is monotonic, so the percentile of the EVs is the EV of the percentile).
"""

from dataclasses import asdict, dataclass

import numpy as np

from picturesq.colour.oklab import rec2020_to_oklab
from picturesq.colour.transfer import FloatArray
from picturesq.normalise.exposure import linear_to_ev, luminance, sample_grid

PERCENTILES = (1, 5, 50, 95, 99)
"""The luminance percentiles in :class:`PhotoStats`."""
CLIP_TOLERANCE = 0.01
"""Relative tolerance of the clip test: a channel at or above ``clip_level * (1 - 0.01)``
counts as clipped. Clipped sensor values don't land exactly on the clip level once white
balance, the camera matrix and demosaicing have mixed them; 1 % is about 0.015 EV."""
EV_DECIMALS = 3
"""Decimals of EV values in :meth:`PhotoStats.to_dict` (a thousandth of a stop)."""
FRACTION_DECIMALS = 5
"""Decimals of fractions and chroma in :meth:`PhotoStats.to_dict`."""


@dataclass(frozen=True)
class PhotoStats:
    """Per-photo stats. Luminance values are in EV relative to mid grey (0.18 = 0 EV)."""

    p1_ev: float
    p5_ev: float
    p50_ev: float
    p95_ev: float
    p99_ev: float
    dynamic_range_ev: float
    """``p99_ev - p1_ev``: the spread of the photo's luminance, ignoring the extreme 1 %."""
    clipped: float
    """Fraction (0 to 1) of sampled pixels with any channel at the clip level."""
    mean_chroma: float
    """Mean Oklab chroma (``hypot(a, b)``): 0 for a grey photo, ~0.1 to 0.2 for vivid colours."""

    def to_dict(self) -> dict[str, float]:
        """JSON-ready, rounded: EV to :data:`EV_DECIMALS`, the rest to :data:`FRACTION_DECIMALS`."""
        return {
            key: round(value, EV_DECIMALS if key.endswith("_ev") else FRACTION_DECIMALS)
            for key, value in asdict(self).items()
        }


def photo_stats(image: FloatArray, clip_level: float) -> PhotoStats:
    """Stats of ``image`` (linear Rec.2020); ``clip_level`` is where the sensor clipped."""
    sample = sample_grid(image)
    luma = luminance(sample).reshape(-1)
    p1, p5, p50, p95, p99 = (
        linear_to_ev(float(value)) for value in np.percentile(luma, PERCENTILES)
    )
    threshold = np.float32(clip_level * (1.0 - CLIP_TOLERANCE))
    # Pairwise maximum: much faster than ``max(axis=-1)`` over a length-3 axis.
    brightest = np.maximum(np.maximum(sample[..., 0], sample[..., 1]), sample[..., 2])
    clipped = float(np.mean(brightest >= threshold))
    lab = rec2020_to_oklab(sample)
    chroma = float(np.mean(np.hypot(lab[..., 1], lab[..., 2])))
    return PhotoStats(
        p1_ev=p1,
        p5_ev=p5,
        p50_ev=p50,
        p95_ev=p95,
        p99_ev=p99,
        dynamic_range_ev=p99 - p1,
        clipped=clipped,
        mean_chroma=chroma,
    )
