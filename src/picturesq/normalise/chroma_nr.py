"""Chroma noise reduction: smooth colour in the shadows, keep every pixel's luminance.

Colour noise is blotchy red/green speckle that is strongest where there is little light.
Our eyes resolve colour much more coarsely than brightness, so smoothing only the colour
removes it without visibly softening the photo. Each pixel keeps its luminance ``Y`` and
takes (some of) the local average *chromaticity*: ``rgb -> rgb + w * (Y * c - rgb)``, where
``c = blur(rgb) / blur(Y)``. We blur a small copy (the blur is wide, so resolution is
wasted on it) and upsample ``c`` a block of rows at a time. The weight ``w`` is full in the
shadows and fades out by ``fade_lightness`` (lightness ``cbrt(Y)``, as Oklab L for greys), so
bright, clean areas keep their colour edges. Measured on the CC0 samples and the reference
set, our darkest tones had ~1.3x the camera JPEG's chroma before this step (ADR-0010).
"""

import numpy as np

from picturesq.colour.filters import gaussian_blur, upsample_rows
from picturesq.colour.spaces import REC2020_TO_XYZ
from picturesq.colour.transfer import FloatArray
from picturesq.config import ChromaNoiseReductionConfig
from picturesq.export.resize import resize_to_long_edge

SMALL_SIGMA = 2.0
"""Blur sigma in pixels of the small copy; its size is set so this equals ``config.radius``."""
BLOCK_ROWS_PIXELS = 1 << 18
_LUMINANCE = REC2020_TO_XYZ[1].astype(np.float32)
_FLOOR = np.float32(1e-6)


def chroma_noise_reduction(image: FloatArray, config: ChromaNoiseReductionConfig) -> FloatArray:
    """Reduce colour noise in ``image`` (linear Rec.2020), in place. Returns ``image``."""
    if config.amount <= 0.0:
        return image
    height, width = image.shape[:2]
    small = resize_to_long_edge(image, max(8, round(SMALL_SIGMA / config.radius)))
    smooth = gaussian_blur(small, SMALL_SIGMA)
    smooth /= np.maximum(smooth @ _LUMINANCE, _FLOOR)[..., None]  # local chromaticity
    span = np.float32(config.fade_lightness - config.full_lightness)
    rows = max(1, BLOCK_ROWS_PIXELS // width)
    for top in range(0, height, rows):
        bottom = min(height, top + rows)
        block = image[top:bottom]
        luminance = block @ _LUMINANCE
        lightness = np.cbrt(np.maximum(luminance, 0.0))
        weight = np.clip((config.fade_lightness - lightness) / span, 0.0, 1.0)
        if not weight.any():
            continue
        np.multiply(weight, np.float32(config.amount), out=weight)
        target = upsample_rows(smooth, height, width, top, bottom)
        np.multiply(target, luminance[..., None], out=target)
        np.subtract(target, block, out=target)
        np.multiply(target, weight[..., None], out=target)
        np.add(block, target, out=block)
    return image
