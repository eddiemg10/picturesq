"""Stage 2, normalise: white balance overrides, exposure, chroma noise reduction, scene
contrast and stats, per photo.

Pure functions, no IO.
"""

from dataclasses import dataclass

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
from picturesq.normalise.scene_contrast import (
    SceneContrastDecision,
    apply_scene_contrast,
    scene_contrast,
    scene_contrast_decision,
)
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


@dataclass(frozen=True)
class NormaliseDecision:
    """What normalise chose for a photo."""

    exposure: ExposureDecision
    scene_contrast: SceneContrastDecision | None
    """None when scene contrast is off for the photo (not measured)."""


def normalise(
    image: FloatArray, config: ProjectConfig, photo: PhotoContext = UNNAMED
) -> FloatArray:
    """Run the normalise stage on ``image`` (linear Rec.2020), in place. Returns ``image``.

    The photo's overrides (``config.photo(photo.name).normalise``) apply: ``enabled``
    replaces ``normalise.enabled``; ``wb_kelvin`` / ``tint`` re-balance the image from the
    as-shot white (``photo.info``) before exposure, raising WhiteBalanceOverrideError
    when that is unknown; ``exposure_ev``, if set, replaces the computed exposure;
    ``scene_contrast``, if set, replaces ``scene_contrast.amount`` (even when it is off).
    """
    normalise_with_decision(image, config, photo)
    return image


def normalise_with_decision(
    image: FloatArray, config: ProjectConfig, photo: PhotoContext = UNNAMED
) -> NormaliseDecision | None:
    """:func:`normalise`, returning what it chose; None if normalise is off.

    With an ``exposure_ev`` override the exposure decision is that value, with no
    correction and never clamped. ``image`` is changed in place, as by :func:`normalise`.

    Order: white balance override, exposure, chroma noise reduction, scene contrast. Scene
    contrast comes last: chroma noise reduction keeps each pixel's luminance, so it measures
    the same range and pivot either way, and chroma noise reduction's fade by lightness
    stays as it was fitted (on the exposed image without scene contrast).
    """
    settings = config.normalise
    overrides = config.photo(photo.name).normalise
    enabled = settings.enabled if overrides.enabled is None else overrides.enabled
    if not enabled:
        return None
    as_shot_xy = None if photo.info is None else photo.info.as_shot_xy
    target_xy = override_white(overrides, as_shot_xy)
    if target_xy is not None and as_shot_xy is not None:
        rebalance_white(image, as_shot_xy, target_xy, out=image)
    if overrides.exposure_ev is None:
        exposure = exposure_decision(image, settings.exposure)
    else:
        exposure = ExposureDecision(ev=overrides.exposure_ev, correction_ev=0.0, clamped=False)
    apply_exposure(image, exposure.ev, out=image)
    chroma_noise_reduction(image, settings.chroma_nr)
    contrast_settings = settings.scene_contrast
    if overrides.scene_contrast is not None:
        amount = overrides.scene_contrast
    else:
        amount = contrast_settings.amount if contrast_settings.enabled else 0.0
    contrast = None
    if amount > 0.0:
        contrast = scene_contrast_decision(image, contrast_settings, amount)
        apply_scene_contrast(
            image, contrast.contrast, contrast.pivot_ev, contrast_settings.soft_limit_ev
        )
    return NormaliseDecision(exposure=exposure, scene_contrast=contrast)


__all__ = [
    "ExposureDecision",
    "Flag",
    "NormaliseDecision",
    "PhotoStats",
    "SceneContrastDecision",
    "WhiteBalanceCheck",
    "WhiteBalanceOverrideError",
    "WhiteEstimate",
    "apply_exposure",
    "apply_scene_contrast",
    "check_white_balance",
    "chroma_noise_reduction",
    "estimate_white_brightest",
    "estimate_white_grey",
    "exposure_decision",
    "exposure_ev",
    "exposure_flags",
    "median_ev",
    "normalise",
    "normalise_with_decision",
    "outlier_flags",
    "override_white",
    "photo_stats",
    "rebalance_white",
    "scene_contrast",
    "scene_contrast_decision",
    "white_balance_flags",
]
