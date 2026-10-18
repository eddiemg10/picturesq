"""The white balance check: does the light in the photo agree with the as-shot white balance?

Normalise keeps the camera's as-shot white balance (plan D6). This module only *checks* it:
it estimates the colour of the light from the photo itself and compares it with the as-shot
white, in mired. Nothing is changed; a disagreement becomes the ``wb_disagreement`` flag
(:func:`picturesq.normalise.flags.white_balance_flags`).

**Two estimators** (illuminant estimation), each guessing which pixels are neutral surfaces:

- **brightest**: the mean colour of the brightest unclipped pixels (98th to 99.9th
  percentile of luminance). Bright things are often white or specular highlights, which
  reflect the light's own colour. Fails when the brightest thing is coloured (a yellow wall,
  a lit sign, a blue sky filling the top of the frame).
- **grey** (grey world on low-saturation pixels): the mean colour of the nearly neutral
  pixels, iterated. Start from the as-shot white; keep the pixels whose saturation (Oklab
  chroma ÷ lightness), after re-balancing for the current estimate, is under
  :data:`GREY_SATURATION` (wider in the first rounds, :data:`GREY_SATURATION_SCHEDULE`);
  average them; repeat. Plain grey world (the mean of all pixels) assumes the scene averages
  to grey and fails on any scene dominated by one colour (a forest, a beach); keeping only
  nearly neutral pixels removes most of that bias. Saturation, not chroma, because chroma
  shrinks with lightness: by chroma alone almost every shadow pixel counts as neutral. Still
  fails when the scene has no neutral surfaces, or when a pale coloured surface (skin, sand,
  warm-lit walls) dominates the near-neutrals.

Both skip clipped pixels (any channel within ``CLIP_TOLERANCE`` of the clip level: a clipped
colour has lost its hue) and pixels more than :data:`DARK_STOPS` below the clip (noise).

**The rule, and why 30 mired.** A single estimator is noisy. On the CC0 samples and the
reference set (7 photos, half-size, 2026-10-18), the white the camera JPEG implies was
within 15 mired of as-shot on every photo (median 2), so as-shot was right; yet each
estimator was 30 or more mired off on some of them (median absolute errors about 17 mired
for brightest, 16 for grey; plain grey world 30). Their errors come from different failure
modes, so the check only **disagrees** when *both* estimates differ from the as-shot white
by at least ``flag_disagreement_mired``, in the *same direction*. Measured on the CC0
samples (brightest / grey, Δmired): dji-fc4382 -13 / -34, fujifilm-x-s10 +25 / +8,
fujifilm-xq1 -15 / -4, pentax-k5iis +28 / +33, pentax-q7 -1 / +4, sony-ilme-fx3 +88 / +87.
At 30 that flags only the Sony; the Pentax tungsten interior (cameras leave tungsten a
little warm on purpose) comes close.

**Where in the pipeline.** The check reads the decoded image (linear Rec.2020, D65), which
the decode has already white-balanced for the as-shot white and adapted to D65: a surface
that is neutral under the as-shot light comes out with R = G = B. A neutral that comes out
with some other colour ``e`` therefore means the light differs from the as-shot one. To get
that light's chromaticity we undo the decode's adaptation: ``e`` → XYZ → Bradford from D65
back to the as-shot white → xy. That is exact for DNGs without forward matrices (the decode
adapts with Bradford) and an approximation otherwise (the camera matrix does the
adaptation). Run it before or after exposure: chromaticity doesn't depend on brightness,
only the clip level does, so pass ``exposure_ev`` if the image has been exposed.

Pure, no IO; 20-40 ms on a 2048 px proxy (both estimators share one ~100k-pixel grid,
:func:`~picturesq.normalise.exposure.sample_grid`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np

from picturesq.colour.oklab import LMS_TO_OKLAB, XYZ_TO_LMS
from picturesq.colour.spaces import D65, REC2020_TO_XYZ
from picturesq.colour.temperature import bradford_matrix, mired, xy_to_kelvin_tint, xyz_to_xy
from picturesq.colour.transfer import FloatArray
from picturesq.config import WhiteBalanceConfig
from picturesq.decode import PhotoInfo
from picturesq.normalise.exposure import luminance, sample_grid
from picturesq.normalise.stats import CLIP_TOLERANCE

XY = tuple[float, float]

MIN_PIXELS: Final = 200
"""An estimator needs at least this many usable pixels in the sample grid, or gives up."""
DARK_STOPS: Final = 8.0
"""Pixels more than this many stops below the clip level are noise-dominated; skipped."""
BRIGHTEST_PERCENTILES: Final = (98.0, 99.9)
"""The luminance percentiles (of usable pixels) the brightest estimator averages between."""
GREY_SATURATION: Final = 0.05
"""Saturation (Oklab chroma ÷ lightness) below which the grey estimator counts a pixel as
nearly neutral. Chroma alone would count almost every dark pixel as neutral, since chroma
shrinks with lightness; 0.05 is a barely visible tint, vivid colours are 0.2 and more."""
GREY_SATURATION_SCHEDULE: Final = (0.15, 0.1, 0.07, GREY_SATURATION, GREY_SATURATION)
"""Saturation limit per iteration of the grey estimator: wide at first, so the neutrals are
still found when the as-shot white is well off, then :data:`GREY_SATURATION`."""
_REC2020_TO_LMS = XYZ_TO_LMS @ REC2020_TO_XYZ
_DIGITS: Final = 1
"""Decimals of kelvin, tint and mired in :meth:`WhiteBalanceCheck.to_dict`."""


def _usable(image: FloatArray, clip_level: float) -> FloatArray:
    """The sample grid's pixels (N x 3) that are unclipped, positive and above the noise."""
    sample = sample_grid(image).reshape(-1, 3)
    brightest = np.maximum(np.maximum(sample[:, 0], sample[:, 1]), sample[:, 2])
    darkest = np.minimum(np.minimum(sample[:, 0], sample[:, 1]), sample[:, 2])
    floor = clip_level * 2.0**-DARK_STOPS
    keep = (brightest < clip_level * (1.0 - CLIP_TOLERANCE)) & (darkest > 0.0)
    keep &= luminance(sample) > floor
    return sample[keep]


def _rgb_to_xy(rgb: np.ndarray) -> XY:
    return xyz_to_xy(REC2020_TO_XYZ @ np.asarray(rgb, dtype=np.float64))


def estimate_white_brightest(image: FloatArray, clip_level: float) -> XY | None:
    """xy of the neutral the brightest unclipped pixels suggest, in ``image``'s own terms.

    ``image`` is linear Rec.2020 (D65); ``clip_level`` is where it clipped. The mean colour
    of the pixels between the :data:`BRIGHTEST_PERCENTILES` of luminance. ``None`` when
    fewer than :data:`MIN_PIXELS` qualify.
    """
    return _brightest(_usable(image, clip_level))


def _brightest(pixels: FloatArray) -> XY | None:
    if len(pixels) < MIN_PIXELS:
        return None
    luma = luminance(pixels)
    low, high = np.percentile(luma, BRIGHTEST_PERCENTILES)
    bright = pixels[(luma >= low) & (luma <= high)]
    if len(bright) == 0:
        return None
    return _rgb_to_xy(bright.mean(axis=0, dtype=np.float64))


def estimate_white_grey(image: FloatArray, clip_level: float) -> XY | None:
    """xy of the neutral the nearly neutral pixels suggest, in ``image``'s own terms.

    Grey world on low-saturation pixels, iterated (:data:`GREY_SATURATION_SCHEDULE`),
    starting from R = G = B (the as-shot white, in a decoded image). Each round re-balances
    the pixels so the current estimate is neutral before measuring their saturation. The
    re-balance is a von Kries scaling of Oklab's cone-like LMS responses, which commutes
    with Oklab's cube root: the root is taken once and each round only scales it.
    ``None`` when fewer than :data:`MIN_PIXELS` are usable or nearly neutral.
    """
    return _grey(_usable(image, clip_level))


def _grey(pixels: FloatArray) -> XY | None:
    if len(pixels) < MIN_PIXELS:
        return None
    # All channels are positive (see _usable), so a power is a safe, faster cube root.
    root = np.power(pixels @ _REC2020_TO_LMS.T.astype(np.float32), np.float32(1.0 / 3.0))
    neutral_lms = _REC2020_TO_LMS @ np.ones(3)
    white = np.ones(3)
    for limit in GREY_SATURATION_SCHEDULE:
        scale = np.cbrt(neutral_lms / (_REC2020_TO_LMS @ white))
        lab = root @ (LMS_TO_OKLAB * scale).T.astype(np.float32)
        # saturation < limit, i.e. a² + b² < (limit L)², without square roots or divisions.
        np.square(lab, out=lab)
        neutral = lab[:, 1] + lab[:, 2] < np.float32(limit**2) * lab[:, 0]
        count = np.count_nonzero(neutral)
        if count < MIN_PIXELS:
            return None
        # The mean of the neutral pixels, as a product: much faster than boolean indexing.
        white = (neutral.astype(np.float32) @ pixels).astype(np.float64) / count
    return _rgb_to_xy(white)


@dataclass(frozen=True)
class WhiteEstimate:
    """One estimator's light, as the scene's white balance, against the as-shot white."""

    kelvin: float
    tint: float
    delta_mired: float
    """Estimate minus as-shot, in mired: positive means the light looks warmer (lower kelvin)
    than the camera assumed, so the photo would look too warm."""
    delta_tint: float
    """Estimate minus as-shot tint (positive is towards magenta)."""

    def to_dict(self) -> dict[str, float]:
        return {
            "kelvin": round(self.kelvin, _DIGITS),
            "tint": round(self.tint, _DIGITS),
            "delta_mired": round(self.delta_mired, _DIGITS),
            "delta_tint": round(self.delta_tint, _DIGITS),
        }


@dataclass(frozen=True)
class WhiteBalanceCheck:
    """The as-shot white balance against the two estimates, and whether they disagree."""

    as_shot_kelvin: float | None
    as_shot_tint: float | None
    brightest: WhiteEstimate | None
    """The brightest estimator's light; ``None`` if it had too few pixels."""
    grey: WhiteEstimate | None
    """The grey estimator's light; ``None`` if it had too few pixels."""
    disagrees: bool
    """Both estimates differ from as-shot by at least ``flag_disagreement_mired``, the same way."""
    reason: str | None = None
    """Why the check couldn't decide (no as-shot white, too few pixels); ``None`` if it could."""

    def to_dict(self) -> dict[str, object]:
        """JSON-ready, kelvin, tint and mired rounded to 0.1."""

        def number(value: float | None) -> float | None:
            return None if value is None else round(value, _DIGITS)

        return {
            "as_shot_kelvin": number(self.as_shot_kelvin),
            "as_shot_tint": number(self.as_shot_tint),
            "brightest": None if self.brightest is None else self.brightest.to_dict(),
            "grey": None if self.grey is None else self.grey.to_dict(),
            "disagrees": self.disagrees,
            "reason": self.reason,
        }


def _scene_estimate(image_xy: XY | None, as_shot_xy: XY) -> WhiteEstimate | None:
    """An estimate in the decoded image's terms → the scene's light, against as-shot."""
    if image_xy is None:
        return None
    to_scene = bradford_matrix(D65, as_shot_xy)
    x, y = image_xy
    xyz = np.array([x / y, 1.0, (1.0 - x - y) / y])
    kelvin, tint = xy_to_kelvin_tint(xyz_to_xy(to_scene @ xyz))
    as_shot_kelvin, as_shot_tint = xy_to_kelvin_tint(as_shot_xy)
    return WhiteEstimate(
        kelvin=kelvin,
        tint=tint,
        delta_mired=mired(kelvin) - mired(as_shot_kelvin),
        delta_tint=tint - as_shot_tint,
    )


def check_white_balance(
    image: FloatArray, info: PhotoInfo, config: WhiteBalanceConfig, *, exposure_ev: float = 0.0
) -> WhiteBalanceCheck:
    """Compare ``image``'s estimated light with the as-shot white in ``info``.

    ``image`` is the decoded photo (linear Rec.2020, D65), multiplied by ``2**exposure_ev``
    if exposure has been applied (that scales the clip level). See the module docstring for
    the rule.
    """
    if info.as_shot_xy is None:
        return WhiteBalanceCheck(None, None, None, None, False, "no as-shot white")
    as_shot_kelvin, as_shot_tint = xy_to_kelvin_tint(info.as_shot_xy)
    clip = info.clip_level * 2.0**exposure_ev
    pixels = _usable(image, clip)
    brightest = _scene_estimate(_brightest(pixels), info.as_shot_xy)
    grey = _scene_estimate(_grey(pixels), info.as_shot_xy)
    if brightest is None or grey is None:
        return WhiteBalanceCheck(
            as_shot_kelvin, as_shot_tint, brightest, grey, False, "too few usable pixels"
        )
    disagrees = estimates_disagree(brightest, grey, config.flag_disagreement_mired)
    return WhiteBalanceCheck(as_shot_kelvin, as_shot_tint, brightest, grey, disagrees)


def estimates_disagree(brightest: WhiteEstimate, grey: WhiteEstimate, limit_mired: float) -> bool:
    """Both estimates at least ``limit_mired`` from as-shot, on the same side (warmer or cooler)."""
    first, second = brightest.delta_mired, grey.delta_mired
    return min(abs(first), abs(second)) >= limit_mired and (first > 0.0) == (second > 0.0)
