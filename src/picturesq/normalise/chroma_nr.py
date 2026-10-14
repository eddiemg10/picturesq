"""Chroma noise reduction: smooth colour (Oklab a/b) in the shadows, keep lightness detail.

Colour noise is blotchy red/green speckle that is strongest where there is little light.
Our eyes resolve colour much more coarsely than brightness, so blurring only ``a``/``b``
removes it without visibly softening the photo. We blur a small copy (the blur is wide, so
resolution is wasted on it), upsample it a block of rows at a time, and blend it in with a
weight that is full in the shadows and fades out by ``fade_lightness``: bright, clean areas
keep their colour edges. Measured on the CC0 samples and the reference set, our darkest
tones had ~1.25x the camera JPEG's chroma before this step (ADR-0010).
"""

import numpy as np

from picturesq.colour.filters import gaussian_blur, upsample_rows
from picturesq.colour.oklab import oklab_to_rec2020, rec2020_to_oklab
from picturesq.colour.transfer import FloatArray
from picturesq.config import ChromaNoiseReductionConfig
from picturesq.export.resize import resize_to_long_edge

SMALL_SIGMA = 2.0
"""Blur sigma in pixels of the small copy; its size is set so this equals ``config.radius``."""
BLOCK_ROWS_PIXELS = 1 << 18


def chroma_noise_reduction(image: FloatArray, config: ChromaNoiseReductionConfig) -> FloatArray:
    """Reduce colour noise in ``image`` (linear Rec.2020), in place. Returns ``image``."""
    if config.amount <= 0.0:
        return image
    height, width = image.shape[:2]
    small_edge = max(8, round(SMALL_SIGMA / config.radius))
    small = resize_to_long_edge(image, small_edge)
    small = rec2020_to_oklab(small, out=small if small is not image else None)
    smooth = gaussian_blur(small[..., 1:], SMALL_SIGMA)
    rows = max(1, BLOCK_ROWS_PIXELS // width)
    for top in range(0, height, rows):
        bottom = min(height, top + rows)
        block = image[top:bottom]
        lab = rec2020_to_oklab(block)
        weight = np.clip(
            (config.fade_lightness - lab[..., :1])
            / (config.fade_lightness - config.full_lightness),
            0.0,
            1.0,
        )
        np.multiply(weight, config.amount, out=weight)
        target = upsample_rows(smooth, height, width, top, bottom)
        lab[..., 1:] += (target - lab[..., 1:]) * weight
        oklab_to_rec2020(lab, out=block)
    return image
