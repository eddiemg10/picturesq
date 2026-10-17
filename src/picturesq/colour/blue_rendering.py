"""Blue rendering: camera-matched skies (ADR-0012). Display-linear Rec.709 in, same out.

Camera JPEGs (DJI's especially) render a blue sky deeper, more colourful and a few degrees
more cyan than an accurate render: the "memory colour" of a sky, which viewers prefer. This
step reproduces it in Oklab, where hue and chroma can be changed without changing each
other: each pixel's **weight** is a raised-cosine window in hue around ``hue`` (zero beyond
``hue_width``, so other hues are exactly untouched) times a smooth ramp in chroma (greys and
whites get none), and at full weight the hue turns by ``hue_shift``,
chroma scales by ``chroma`` and lightness by ``lightness``. Pixels the change pushes out of
the display gamut are brought back at constant hue and lightness.
"""

import numpy as np

from picturesq.colour.oklab import fit_gamut_oklab, rec709_to_oklab
from picturesq.colour.transfer import FloatArray
from picturesq.config import BlueRenderingConfig


def blue_rendering_weight(lab: FloatArray, config: BlueRenderingConfig) -> FloatArray:
    """How strongly each Oklab pixel (N, 3) is adjusted, in [0, 1]."""
    a, b = lab[:, 1], lab[:, 2]
    chroma = np.hypot(a, b)
    hue = np.degrees(np.arctan2(b, a))
    distance = (hue - config.hue + 180.0) % 360.0 - 180.0
    ramp = np.clip(
        (chroma - config.chroma_start) / (config.chroma_full - config.chroma_start), 0.0, 1.0
    )
    window = np.clip(np.abs(distance) / config.hue_width, 0.0, 1.0)
    weight = np.where(window < 1.0, np.cos(0.5 * np.pi * window) ** 2, 0.0)
    weight *= ramp * ramp * (3.0 - 2.0 * ramp)  # smoothstep: no kink at chroma_start
    return weight.astype(lab.dtype)


def blue_rendering(rgb: FloatArray, config: BlueRenderingConfig) -> FloatArray:
    """Apply blue rendering to display-linear Rec.709 pixels (N, 3) in [0, 1], in place."""
    if not config.enabled:
        return rgb
    lab = rec709_to_oklab(rgb)
    weight = blue_rendering_weight(lab, config)
    touched = weight > 0.0
    if not touched.any():
        return rgb
    lab, weight = lab[touched], weight[touched]
    angle = np.radians(config.hue_shift) * weight
    cos, sin = np.cos(angle), np.sin(angle)
    gain = np.power(np.float32(config.chroma), weight)
    a = (lab[:, 1] * cos - lab[:, 2] * sin) * gain
    b = (lab[:, 1] * sin + lab[:, 2] * cos) * gain
    lab[:, 0] *= np.power(np.float32(config.lightness), weight)
    lab[:, 1], lab[:, 2] = a, b
    rgb[touched] = fit_gamut_oklab(lab)
    return rgb
