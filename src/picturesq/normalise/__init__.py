"""Stage 2, normalise: exposure, chroma noise reduction and stats, per photo.

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

    The photo's ``exposure_ev`` override, if set, replaces the computed exposure.
    """
    settings = config.normalise
    if not settings.enabled:
        return image
    ev = config.photo(photo.name).normalise.exposure_ev
    if ev is None:
        ev = exposure_ev(image, settings.exposure)
    apply_exposure(image, ev, out=image)
    return chroma_noise_reduction(image, settings.chroma_nr)


__all__ = [
    "ExposureDecision",
    "Flag",
    "PhotoStats",
    "WhiteBalanceCheck",
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
    "photo_stats",
    "white_balance_flags",
]
