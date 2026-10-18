"""Stage 2, normalise: white balance overrides, exposure, chroma noise reduction and stats,
per photo.

Pure functions, no IO.
"""

from picturesq.colour.transfer import FloatArray
from picturesq.config import ProjectConfig
from picturesq.normalise.chroma_nr import chroma_noise_reduction
from picturesq.normalise.exposure import (
    ExposureDecision,
    apply_exposure,
    exposure_decision,
    exposure_ev,
    median_ev,
)
from picturesq.normalise.flags import Flag, exposure_flags, outlier_flags, white_balance_flags
from picturesq.normalise.stats import PhotoStats, photo_stats
from picturesq.normalise.white_balance import (
    WhiteBalanceOverrideError,
    override_white,
    rebalance_white,
)
from picturesq.normalise.white_balance_check import (
    WhiteBalanceCheck,
    WhiteEstimate,
    check_white_balance,
    estimate_white_brightest,
    estimate_white_grey,
)
from picturesq.photo import UNNAMED, PhotoContext


def normalise(
    image: FloatArray, config: ProjectConfig, photo: PhotoContext = UNNAMED
) -> FloatArray:
    """Run the normalise stage on ``image`` (linear Rec.2020), in place. Returns ``image``.

    The photo's overrides (``config.photo(photo.name).normalise``) apply: ``enabled``
    replaces ``normalise.enabled``; ``wb_kelvin`` / ``tint`` re-balance the image from the
    as-shot white (``photo.info``) before exposure, raising WhiteBalanceOverrideError
    when that is unknown; ``exposure_ev``, if set, replaces the computed exposure.
    """
    settings = config.normalise
    overrides = config.photo(photo.name).normalise
    enabled = settings.enabled if overrides.enabled is None else overrides.enabled
    if not enabled:
        return image
    as_shot_xy = None if photo.info is None else photo.info.as_shot_xy
    target_xy = override_white(overrides, as_shot_xy)
    if target_xy is not None and as_shot_xy is not None:
        rebalance_white(image, as_shot_xy, target_xy, out=image)
    ev = overrides.exposure_ev
    if ev is None:
        ev = exposure_ev(image, settings.exposure)
    apply_exposure(image, ev, out=image)
    return chroma_noise_reduction(image, settings.chroma_nr)


__all__ = [
    "ExposureDecision",
    "Flag",
    "PhotoStats",
    "WhiteBalanceCheck",
    "WhiteBalanceOverrideError",
    "WhiteEstimate",
    "apply_exposure",
    "check_white_balance",
    "chroma_noise_reduction",
    "estimate_white_brightest",
    "estimate_white_grey",
    "exposure_decision",
    "exposure_ev",
    "exposure_flags",
    "median_ev",
    "normalise",
    "outlier_flags",
    "override_white",
    "photo_stats",
    "rebalance_white",
    "white_balance_flags",
]
