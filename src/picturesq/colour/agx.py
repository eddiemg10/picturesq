"""AgX-style display transform (ADR-0003): scene-linear Rec.2020 → display-linear Rec.709.

Four steps, written from the published description of AgX (Troy Sobotka) with our own
parameterisation and defaults (ADR-0007):

1. **Inset.** Re-read the pixel's Rec.709 values as if they were values in a smaller,
   *inset* gamut (primaries pulled toward white) and convert them back to
   Rec.709. Every channel picks up a little of the others, so colours get slightly less
   saturated and most slightly-out-of-gamut colours (negative channels) become positive.
2. **Log encode.** Each channel becomes its EV relative to mid grey, mapped from
   ``[min_ev, max_ev]`` to ``[0, 1]``.
3. **Sigmoid.** An S-curve through mid grey takes the log values to display-encoded values:
   a toe toward black, a slope set by ``contrast``, and a shoulder that rolls highlights
   off toward white instead of clipping. Because the curve runs *per channel*, a bright
   saturated colour's channels converge as they approach 1, so it fades toward white with
   its hue intact (the "path to white") instead of clipping to a brighter, skewed hue.
4. **Outset.** Decode the curve's output with the sRGB curve, then apply the inverse of an
   inset matrix to give back some of the saturation the inset removed.

Two finishing steps match the result to camera rendering (ADR-0010):

5. **Chroma preservation.** Blend with a render that tone-maps luminance only and keeps
   each pixel's RGB ratios. Per-channel curves wash bright colours out much faster than
   cameras do (a blue sky at 70 % display brightness kept a third of the camera's chroma);
   the blend keeps highlights colourful while bright colours still reach white at the top.
6. **Saturation.** Scale chroma around each pixel's luminance, then pull any channel that
   left ``[0, 1]`` back toward grey of the same luminance (hue kept).

Greys are untouched by the matrices (white maps to white), so a grey ramp only sees the curve:
scene 0.18 maps to display 0.18.
"""

from dataclasses import dataclass, replace

import numpy as np
from numpy.typing import NDArray

from picturesq.colour.spaces import (
    REC709,
    REC709_TO_XYZ,
    REC2020_TO_REC709,
    REC2020_TO_XYZ,
    Matrix,
    RgbSpace,
    apply_matrix,
    rgb_to_rgb_matrix,
)
from picturesq.colour.transfer import (
    EV_FLOOR,
    MIDDLE_GREY,
    SRGB_GREY_ENCODED,
    SRGB_GREY_SLOPE_PER_EV,
    FloatArray,
    srgb_decode,
)
from picturesq.config import DisplayTransformConfig

PerPrimary = tuple[float, float, float]

TABLE_SIZE = 4096
"""Samples of the curve (sigmoid then sRGB decode) that ``agx`` interpolates between.

Linear interpolation between 4096 samples of this smooth curve is within ~2e-6 of the
exact maths (tested), far below an 8-bit step, and ~20x faster than evaluating the powers
per pixel (about 1 s instead of 21 s on a 32 MP image).
"""
BLOCK_PIXELS = 1 << 18
"""``agx`` works through the image in blocks this size, so its temporaries stay small."""

_REC2020_LUMINANCE = REC2020_TO_XYZ[1].astype(np.float32)
_REC709_LUMINANCE = REC709_TO_XYZ[1].astype(np.float32)


def inset_space(base: RgbSpace, inset: PerPrimary) -> RgbSpace:
    """``base`` with each primary moved toward white along a straight line in xy.

    ``inset`` 0 keeps the primary where it is; 0.2 moves it a fifth of the way to white.
    (AgX descriptions also rotate the primaries; on our hue-drift measurement that gained
    under 0.2° RMS, so we don't.)
    """
    wx, wy = base.white

    def move(xy: tuple[float, float], amount: float) -> tuple[float, float]:
        return wx + (1.0 - amount) * (xy[0] - wx), wy + (1.0 - amount) * (xy[1] - wy)

    red, green, blue = (
        move(xy, amount)
        for xy, amount in zip((base.red, base.green, base.blue), inset, strict=True)
    )
    return RgbSpace(f"{base.name}-inset", red, green, blue, base.white)


@dataclass(frozen=True, eq=False)
class AgxCurve:
    """Everything the transform needs, derived once from a DisplayTransformConfig."""

    inset_matrix: Matrix
    """Working space (Rec.2020) → inset Rec.709, applied before the curve."""
    outset_matrix: Matrix
    """Inset Rec.709 → Rec.709, applied after the curve (in display-linear)."""
    min_ev: float
    range_ev: float
    pivot_x: float
    """Mid grey's position on the log axis."""
    pivot_y: float
    """Mid grey's display-encoded value."""
    slope: float
    """The curve's slope at the pivot, in display-encoded units per log-axis unit."""
    toe_power: float
    toe_limit: float
    shoulder_power: float
    shoulder_limit: float
    table: NDArray[np.float32]
    """``srgb_decode(sigmoid(x))`` at ``TABLE_SIZE`` evenly spaced x in ``[0, 1]``."""
    table_step: NDArray[np.float32]
    """``table[i + 1] - table[i]`` (0 after the last sample), for interpolation."""
    chroma_preservation: float
    saturation: float
    saturation_fade: float

    @classmethod
    def from_config(cls, config: DisplayTransformConfig) -> "AgxCurve":
        range_ev = config.max_ev - config.min_ev
        pivot_x = -config.min_ev / range_ev
        pivot_y = SRGB_GREY_ENCODED
        slope = config.contrast * SRGB_GREY_SLOPE_PER_EV * range_ev
        inset = inset_space(REC709, config.inset)
        outset = inset_space(REC709, config.outset)
        curve = cls(
            inset_matrix=rgb_to_rgb_matrix(inset, REC709) @ REC2020_TO_REC709,
            outset_matrix=rgb_to_rgb_matrix(REC709, outset),
            min_ev=config.min_ev,
            range_ev=range_ev,
            pivot_x=pivot_x,
            pivot_y=pivot_y,
            slope=slope,
            toe_power=config.toe,
            toe_limit=_limit(slope * pivot_x, pivot_y, config.toe),
            shoulder_power=config.shoulder,
            shoulder_limit=_limit(slope * (1.0 - pivot_x), 1.0 - pivot_y, config.shoulder),
            chroma_preservation=config.chroma_preservation,
            saturation=config.saturation,
            saturation_fade=config.saturation_fade,
            table=np.empty(0, dtype=np.float32),
            table_step=np.empty(0, dtype=np.float32),
        )
        table = srgb_decode(sigmoid(np.linspace(0.0, 1.0, TABLE_SIZE), curve))
        step = np.append(np.diff(table), 0.0)
        return replace(curve, table=table.astype(np.float32), table_step=step.astype(np.float32))


def _limit(reach: float, target: float, power: float) -> float:
    """The asymptote ``a`` of ``bend(t) = (t**-p + a**-p) ** (-1/p)`` with ``bend(reach) = target``.

    ``bend`` starts with slope 1 and flattens toward ``a``; ``reach`` is where a straight line
    at the pivot slope would be at the end of the axis, and ``target`` is how far the curve
    must actually travel (to black or white). The config validator guarantees reach > target.
    """
    return float((target**-power - reach**-power) ** (-1.0 / power))


def sigmoid(x: FloatArray, curve: AgxCurve, out: FloatArray | None = None) -> FloatArray:
    """Log-axis values in ``[0, 1]`` → display-encoded values in ``[0, 1]``.

    Each side of the pivot is ``pivot_y ± bend(slope * |x - pivot_x|)``, with its own power
    (sharpness) and limit chosen so the curve ends exactly at (0, 0) and (1, 1). Monotonic,
    slope ``curve.slope`` at the pivot.
    """
    out = np.subtract(x, curve.pivot_x, out=out)
    above = out >= 0.0
    below = np.logical_not(above)
    np.abs(out, out=out)
    np.multiply(out, curve.slope, out=out)
    with np.errstate(divide="ignore"):  # 0 ** -p = inf, and inf ** (-1/p) = 0: correct
        for mask, power, limit in (
            (above, curve.shoulder_power, curve.shoulder_limit),
            (below, curve.toe_power, curve.toe_limit),
        ):
            np.power(out, -power, out=out, where=mask)
            np.add(out, limit**-power, out=out, where=mask)
            np.power(out, -1.0 / power, out=out, where=mask)
    np.negative(out, out=out, where=below)
    np.add(out, curve.pivot_y, out=out)
    return np.clip(out, 0.0, 1.0, out=out)


def agx(image: FloatArray, curve: AgxCurve, out: FloatArray | None = None) -> FloatArray:
    """Scene-linear Rec.2020 → display-linear Rec.709 in ``[0, 1]``.

    Pass ``out`` (which may be ``image`` itself) to avoid allocating a new array.
    """
    if out is None:
        out = np.empty_like(image)
    elif out.shape != image.shape:
        raise ValueError(f"out has shape {out.shape}, expected {image.shape}")
    if image.shape[-1] != 3:
        raise ValueError(f"expected 3 channels in the last axis, got shape {image.shape}")
    if not (image.flags.c_contiguous and out.flags.c_contiguous):
        _agx_block(image, curve, out)
        return out
    pixels, results = image.reshape(-1, 3), out.reshape(-1, 3)  # views, not copies
    for start in range(0, len(pixels), BLOCK_PIXELS):
        block = slice(start, start + BLOCK_PIXELS)
        _agx_block(pixels[block], curve, results[block])
    return out


def _lookup(x: FloatArray, curve: AgxCurve) -> None:
    """Replace ``x`` (in ``[0, 1]``) by the curve, interpolating linearly in the table."""
    np.multiply(x, len(curve.table) - 1, out=x)
    index = x.astype(np.intp)  # floor, since x >= 0
    np.subtract(x, index, out=x, casting="unsafe")  # fraction between two samples
    np.multiply(x, np.take(curve.table_step, index), out=x)
    np.add(x, np.take(curve.table, index), out=x)


def _log_encode(values: FloatArray, curve: AgxCurve) -> None:
    """Replace scene-linear ``values`` by their position on the curve's log axis, in [0, 1].

    ``(log2(v / mid grey) - min_ev) / range_ev``, folded into one multiply-add. Negatives and
    zeros clamp to the EV floor, far below min_ev, so they end up at 0.
    """
    np.maximum(values, EV_FLOOR, out=values)
    np.log2(values, out=values)
    np.multiply(values, 1.0 / curve.range_ev, out=values)
    np.add(values, -(np.log2(MIDDLE_GREY) + curve.min_ev) / curve.range_ev, out=values)
    np.clip(values, 0.0, 1.0, out=values)


def _fit_gamut(rgb: FloatArray, luminance: FloatArray) -> None:
    """Pull pixels with a channel outside [0, 1] toward grey of the same luminance (in place).

    ``luminance`` has shape (..., 1) and must lie in [0, 1]. Moving along the line to grey
    keeps the hue (in linear RGB) and the luminance; only chroma is given up. Only the
    (usually few) pixels outside the range are touched.
    """
    # Element-wise over the three planes: numpy's max/min over a length-3 axis is ~10x slower.
    red, green, blue = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    high = np.maximum(np.maximum(red, green), blue)
    low = np.minimum(np.minimum(red, green), blue)
    outside = (high > 1.0) | (low < 0.0)
    if not outside.any():
        return
    pixels = rgb[outside]
    grey = luminance[..., 0][outside][:, None]
    high, low = high[outside][:, None], low[outside][:, None]
    scale = np.ones_like(high)
    with np.errstate(divide="ignore", invalid="ignore"):
        np.minimum(scale, (1.0 - grey) / (high - grey), out=scale, where=high > 1.0)
        np.minimum(scale, grey / (grey - low), out=scale, where=low < 0.0)
    np.maximum(scale, 0.0, out=scale)
    rgb[outside] = grey + (pixels - grey) * scale


def _keep_ratios(image: FloatArray, curve: AgxCurve) -> FloatArray:
    """Tone-map luminance only, keeping each pixel's RGB ratios: Rec.709 display-linear."""
    luminance = image @ _REC2020_LUMINANCE
    np.maximum(luminance, EV_FLOOR, out=luminance)
    display = luminance.copy()
    _log_encode(display, curve)
    _lookup(display, curve)
    rgb = apply_matrix(image, REC2020_TO_REC709)
    np.multiply(rgb, (display / luminance)[..., None], out=rgb)
    _fit_gamut(rgb, display[..., None])
    return rgb


def _saturate(rgb: FloatArray, amount: float, fade: float) -> None:
    """Scale chroma around each pixel's luminance, then fit the gamut (in place).

    The scale is ``amount`` at black and moves toward 1 as luminance rises, reaching
    ``1 + (amount - 1) * (1 - fade)`` at white: bright colours are already near the edge of
    the gamut, and boosting them only pushes a channel against 1.
    """
    luminance = np.clip(rgb @ _REC709_LUMINANCE, 0.0, 1.0)[..., None]
    scale = 1.0 + (amount - 1.0) * (1.0 - fade * luminance)
    np.subtract(rgb, luminance, out=rgb)
    np.multiply(rgb, scale, out=rgb)
    np.add(rgb, luminance, out=rgb)
    _fit_gamut(rgb, luminance)


def _agx_block(image: FloatArray, curve: AgxCurve, out: FloatArray) -> None:
    # Computed first: `out` may be `image`.
    kept = _keep_ratios(image, curve) if curve.chroma_preservation > 0.0 else None
    apply_matrix(image, curve.inset_matrix, out=out)
    _log_encode(out, curve)
    _lookup(out, curve)  # sigmoid, then sRGB decode to display-linear
    apply_matrix(out, curve.outset_matrix, out=out)
    np.clip(out, 0.0, 1.0, out=out)
    if kept is not None:
        np.multiply(out, 1.0 - curve.chroma_preservation, out=out)
        np.multiply(kept, curve.chroma_preservation, out=kept)
        np.add(out, kept, out=out)
    if curve.saturation != 1.0:
        _saturate(out, curve.saturation, curve.saturation_fade)
    np.clip(out, 0.0, 1.0, out=out)
