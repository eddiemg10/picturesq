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
from picturesq.normalise.flags import Flag, exposure_flags, outlier_flags
from picturesq.normalise.stats import PhotoStats, photo_stats
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
    "apply_exposure",
    "chroma_noise_reduction",
    "exposure_decision",
    "exposure_ev",
    "exposure_flags",
    "median_ev",
    "normalise",
    "outlier_flags",
    "photo_stats",
]
