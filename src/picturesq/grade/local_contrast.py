"""Local contrast: keep detail where the display transform's curve flattens it.

The display transform maps every pixel through one curve. Where that curve is flat (the
shoulder, where a bright sky sits, and the toe) it compresses *everything* there, including
the small brightness differences that are the detail: clouds against sky, haze between
distant hills. A camera JPEG keeps far more of that (the DJI sample's sky had ~4x our local
contrast, ADR-0011).

We split log luminance into a smooth **base** (broad areas) and **detail** (the rest):
``L = B + (L - B)``. The curve still decides how bright each broad area ends up; only the
detail is amplified, by ``m = max(slope(B), detail_floor) * amount / slope(B)``, where
``slope(B)`` is the curve's slope at the base (display stops per scene stop, luminance
only). After the curve, detail above mid grey therefore keeps a slope of at least
``detail_floor``; in the shadows only ``amount`` applies (the toe is flat too, but what it
hides there is mostly noise).
Every channel is scaled by the same gain, so hue and colour ratios are kept. Only small
detail is amplified fully: the added stops are ``(m - 1) * limit * tanh((L - B) / limit)``,
which levels off for detail much larger than ``detail_limit_ev``. Cloud texture is a few
tenths of a stop; a sun glint is several stops and would otherwise be pushed into white.

The base is an edge-aware blur (``edge_aware_blur``, a domain transform filter) so that a
large, sharp step like a horizon stays in the base and gets no halo. It is computed on a
small copy of log luminance and brought back to full resolution by joint bilateral
upsampling: each pixel takes the base of its four nearest small pixels, weighted by
distance *and* by how close their brightness is to its own, so a pixel just above a
horizon never takes the base of the ground below it. This runs a block of rows at a time.
"""

from functools import partial

import numpy as np
from PIL import Image

from picturesq import parallel
from picturesq.colour.agx import AgxCurve, _log_encode, _lookup
from picturesq.colour.filters import edge_aware_blur
from picturesq.colour.spaces import REC2020_TO_XYZ
from picturesq.colour.transfer import EV_FLOOR, MIDDLE_GREY, FloatArray
from picturesq.config import DisplayTransformConfig, LocalContrastConfig

SMALL_LONG_EDGE = 512
"""Long edge of the copy the base is computed on (the base is smooth; more is wasted)."""
_LUMINANCE = REC2020_TO_XYZ[1].astype(np.float32)
_SLOPE_GRID = np.linspace(-14.0, 14.0, 561)
"""Scene EVs at which the curve's slope is tabulated (0.05 EV apart)."""


def curve_slope(display: DisplayTransformConfig) -> tuple[FloatArray, FloatArray]:
    """``(ev, slope)``: the display transform's luminance curve slope in display EV per scene EV.

    Tabulated on ``_SLOPE_GRID``; mid grey is EV 0.
    """
    curve = AgxCurve.from_config(display)
    values = (MIDDLE_GREY * 2.0**_SLOPE_GRID).astype(np.float32)
    _log_encode(values, curve)
    _lookup(values, curve)
    log_display = np.log2(np.maximum(values, EV_FLOOR))
    slope = np.gradient(log_display, _SLOPE_GRID)
    return _SLOPE_GRID.astype(np.float32), slope.astype(np.float32)


def log_luminance(rgb: FloatArray) -> FloatArray:
    return np.log2(np.maximum(rgb @ _LUMINANCE, EV_FLOOR) / np.float32(MIDDLE_GREY))


class BaseUpsampler:
    """Joint bilateral upsampling of a small base to full resolution, a block of rows at a time.

    Each of a pixel's four bilinear neighbours is also weighted by
    ``exp(-(L - L_small)**2 / (2 * edge_ev**2))``. A pixel unlike all four (a thin bright
    wire) gets its own luminance as base: no detail, so no change. The small planes are
    widened to full width once (cheap: a few hundred rows), so each block only picks rows.
    """

    def __init__(
        self, base: FloatArray, small: FloatArray, height: int, width: int, edge_ev: float
    ) -> None:
        h, w = small.shape
        xs = (np.arange(width) + 0.5) * (w / width) - 0.5
        x0 = np.clip(np.floor(xs).astype(np.intp), 0, w - 1)
        x1 = np.minimum(x0 + 1, w - 1)
        fx = np.clip(xs - x0, 0.0, 1.0).astype(np.float32)
        planes = np.stack([small, base], axis=-1)  # gathered together: one index per side
        self._left, self._right = planes[:, x0], planes[:, x1]
        self._fx = fx
        self._h, self._height = h, height
        self._scale = np.float32(-0.5 / edge_ev**2)

    def rows(self, log_luminance: FloatArray, top: int) -> FloatArray:
        """The base for rows ``top:top + len(log_luminance)``, given their log luminance."""
        h = self._h
        ys = (np.arange(top, top + log_luminance.shape[0]) + 0.5) * (h / self._height) - 0.5
        y0 = np.clip(np.floor(ys).astype(np.intp), 0, h - 1)
        y1 = np.minimum(y0 + 1, h - 1)
        fy = np.clip(ys - y0, 0.0, 1.0).astype(np.float32)[:, None]
        total = np.float32(1e-6) * log_luminance
        weights = np.full_like(log_luminance, np.float32(1e-6))  # the fallback's weight
        for rows, wy in ((y0, 1.0 - fy), (y1, fy)):
            for columns, wx in ((self._left, 1.0 - self._fx), (self._right, self._fx)):
                neighbour = columns[rows]
                weight = np.subtract(log_luminance, neighbour[..., 0])
                np.square(weight, out=weight)
                np.multiply(weight, self._scale, out=weight)
                np.exp(weight, out=weight)
                np.multiply(weight, wy * wx, out=weight)
                weights += weight
                np.multiply(weight, neighbour[..., 1], out=weight)
                total += weight
        np.divide(total, weights, out=total)
        return total


def luminance_base(image: FloatArray, radius: float, edge_ev: float) -> BaseUpsampler:
    """The smooth base of ``image``'s log luminance (stops from mid grey), ready to read a
    block of rows at a time: an edge-aware blur of spatial scale ``radius`` (a fraction of
    the long edge) on a small copy, kept from crossing steps much larger than ``edge_ev``.
    """
    height, width = image.shape[:2]
    scale = min(1.0, SMALL_LONG_EDGE / max(height, width))
    small_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    log_luminance = _log_luminance_in_blocks(image)
    small = Image.fromarray(log_luminance, "F").resize(small_size, Image.Resampling.BOX)
    del log_luminance
    small_luminance = np.asarray(small, dtype=np.float32)
    sigma = max(1.0, radius * max(small_luminance.shape))
    base_small = edge_aware_blur(small_luminance, sigma, edge_ev)
    return BaseUpsampler(base_small, small_luminance, height, width, edge_ev)


def local_contrast(
    image: FloatArray, config: LocalContrastConfig, display: DisplayTransformConfig
) -> FloatArray:
    """Amplify detail where ``display``'s curve compresses it, in place. Returns ``image``.

    ``image`` is scene-linear Rec.2020; ``display`` is the transform it will be viewed
    through (its curve decides how much each tone is compressed).
    """
    if not config.enabled:
        return image
    height, width = image.shape[:2]
    upsampler = luminance_base(image, config.radius, config.edge_ev)
    ev, slope = curve_slope(display)
    floor, amount = np.float32(config.detail_floor), np.float32(config.amount)
    limit = np.float32(config.detail_limit_ev)
    limit_inverse = np.float32(1.0 / config.detail_limit_ev)

    def amplify_rows(top: int, bottom: int) -> None:
        block = image[top:bottom]
        lum = log_luminance(block)
        base = upsampler.rows(lum, top)
        base_slope = np.maximum(np.interp(base, ev, slope).astype(np.float32), np.float32(1e-3))
        # The floor applies above mid grey only: in the toe it would amplify shadow noise.
        target = np.where(base > 0.0, np.maximum(base_slope, floor), base_slope)
        gain = target * amount / base_slope
        np.clip(gain, 0.0, np.float32(config.max_gain), out=gain)
        # Detail is (lum - base) stops; scaling it by `gain` adds (gain - 1) * detail stops.
        np.subtract(lum, base, out=lum)
        # Only small detail is amplified: the added part saturates at (gain - 1) * limit
        # stops, so a glint several stops above its surroundings isn't pushed into white.
        np.multiply(lum, limit_inverse, out=lum)
        np.tanh(lum, out=lum)
        np.multiply(lum, (gain - 1.0) * limit, out=lum)
        np.exp2(lum, out=lum)
        np.multiply(block, lum[..., None], out=block)

    parallel.run(partial(amplify_rows, *rows) for rows in parallel.row_blocks(height, width))
    return image


def _log_luminance_in_blocks(image: FloatArray) -> FloatArray:
    height, width = image.shape[:2]
    out = np.empty((height, width), dtype=np.float32)

    def rows(top: int, bottom: int) -> None:
        out[top:bottom] = log_luminance(image[top:bottom])

    parallel.run(partial(rows, *block) for block in parallel.row_blocks(height, width))
    return out
