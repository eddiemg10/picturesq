"""Scene contrast: extra contrast for flat scenes, as cameras add (ADR-0017).

A camera JPEG of a flat scene (overcast, fog, a low-contrast subject) has more contrast than
the same scene through a fixed tone curve: on the two flat photos of the reference set the
camera's tones were 1.4-1.5x steeper than ours (#60). Scenes with a normal range showed no
such pattern, so only flat scenes are changed.

How flat a scene is: its **range**, ``p95 - p5`` of luminance in EV (the 5th to 95th
percentile, so a few specular highlights or black pixels don't count). The extra contrast:

    contrast = amount * clamp(target_range_ev / range - 1, 0, max_contrast)

zero for scenes at least ``target_range_ev`` wide. Each pixel then moves, in stops,

    added_ev = contrast * soft_limit_ev * tanh((ev - pivot_ev) / soft_limit_ev)

where ``ev`` is its luminance in EV and ``pivot_ev`` the scene's ``pivot_percentile``. Near
the pivot the slope is ``1 + contrast`` (0.25 = 25 % steeper); far from it the move levels
off at ``contrast * soft_limit_ev`` stops, so deep shadows and highlights are not pushed
without limit. R, G and B are multiplied by the same ``2**added_ev``: luminance changes and
the channel ratios (hue and saturation) stay as they were; greys stay grey.

The pivot is high (p75 by default) because the camera kept a flat scene's bright end where
we put it and pushed the darker tones down.

Pure functions, no IO.
"""

from dataclasses import dataclass
from functools import partial

import numpy as np

from picturesq import parallel
from picturesq.colour.spaces import REC2020_TO_XYZ
from picturesq.colour.transfer import EV_FLOOR, MIDDLE_GREY, FloatArray
from picturesq.config import SceneContrastConfig
from picturesq.normalise.exposure import linear_to_ev, luminance, sample_grid

RANGE_PERCENTILES = (5.0, 95.0)
"""The luminance percentiles whose difference is a scene's range."""
_LUMINANCE = REC2020_TO_XYZ[1].astype(np.float32)
_LUMINANCE_FLOOR = np.float32(EV_FLOOR)
_INVERSE_GREY = np.float32(1.0 / MIDDLE_GREY)


@dataclass(frozen=True)
class SceneContrastDecision:
    """How normalise chose a photo's scene contrast."""

    contrast: float
    """The extra contrast applied: 0 = none, 0.25 = tones near the pivot 25 % steeper."""
    range_ev: float
    """The scene's range: ``p95 - p5`` of its luminance, in EV."""
    pivot_ev: float
    """The luminance that stays put, in EV relative to mid grey."""


def scene_contrast(range_ev: float, config: SceneContrastConfig, amount: float) -> float:
    """The extra contrast for a scene whose range is ``range_ev`` (``p95 - p5``, in EV).

    ``amount * clamp(target_range_ev / range_ev - 1, 0, max_contrast)``; ``amount`` is
    ``config.amount`` or a photo's override. A range of 0 or less (a uniform photo) gets
    the full ``max_contrast``.
    """
    if amount <= 0.0:
        return 0.0
    if range_ev <= 0.0:
        return amount * config.max_contrast
    wanted = config.target_range_ev / range_ev - 1.0
    return amount * float(np.clip(wanted, 0.0, config.max_contrast))


def scene_contrast_decision(
    image: FloatArray, config: SceneContrastConfig, amount: float
) -> SceneContrastDecision:
    """Measure ``image`` (linear Rec.2020) and choose its scene contrast.

    The percentiles use the same sample grid as the exposure's median. They are taken in
    scene-linear and expressed in EV (``log2`` is monotonic, so it's the same thing).
    """
    luma = luminance(sample_grid(image)).reshape(-1)
    p5, p95, pivot = (
        linear_to_ev(float(value))
        for value in np.percentile(luma, (*RANGE_PERCENTILES, config.pivot_percentile))
    )
    range_ev = p95 - p5
    return SceneContrastDecision(
        contrast=scene_contrast(range_ev, config, amount), range_ev=range_ev, pivot_ev=pivot
    )


def apply_scene_contrast(
    image: FloatArray, contrast: float, pivot_ev: float, soft_limit_ev: float
) -> FloatArray:
    """Add ``contrast`` around ``pivot_ev`` to ``image`` (linear Rec.2020), in place.

    Each pixel's R, G and B are multiplied by
    ``2**(contrast * soft_limit_ev * tanh((ev - pivot_ev) / soft_limit_ev))``, ``ev`` being
    its luminance in EV relative to mid grey (clamped at ``EV_FLOOR``). Works a block of
    rows at a time. ``contrast`` 0 leaves ``image`` untouched. Returns ``image``.
    """
    if contrast <= 0.0:
        return image
    height, width = image.shape[:2]
    inverse_limit = np.float32(1.0 / soft_limit_ev)
    pivot = np.float32(pivot_ev)
    scale = np.float32(contrast * soft_limit_ev)

    def contrast_rows(top: int, bottom: int) -> None:
        block = image[top:bottom]
        gain = block @ _LUMINANCE
        np.maximum(gain, _LUMINANCE_FLOOR, out=gain)
        np.multiply(gain, _INVERSE_GREY, out=gain)
        np.log2(gain, out=gain)
        np.subtract(gain, pivot, out=gain)
        np.multiply(gain, inverse_limit, out=gain)
        np.tanh(gain, out=gain)
        np.multiply(gain, scale, out=gain)
        np.exp2(gain, out=gain)
        np.multiply(block, gain[..., None], out=block)

    parallel.run(partial(contrast_rows, *rows) for rows in parallel.row_blocks(height, width))
    return image
