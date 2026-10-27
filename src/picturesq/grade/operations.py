"""Operations: the pure image functions behind a look's steps (plan §4.3, ADR-0019).

Each function takes a float32 image (HxWx3, linear Rec.2020 for scene operations) and its
operation's model, and changes the image in place, a block of pixels at a time on several
cores. :func:`apply_operation` scales the operation by intensity first and skips it when
that leaves it neutral, so intensity 0 is exactly the input, bit for bit.
"""

from collections.abc import Callable, Iterable
from functools import partial
from typing import Any

import numpy as np

from picturesq import parallel
from picturesq.colour.oklab import oklab_to_rec2020, rec2020_to_oklab
from picturesq.colour.spaces import D65, REC2020_TO_XYZ, apply_matrix
from picturesq.colour.temperature import (
    kelvin_tint_to_xy,
    mired,
    white_balance_matrix,
    xy_to_kelvin_tint,
)
from picturesq.colour.transfer import EV_FLOOR, MIDDLE_GREY, FloatArray, srgb_decode, srgb_encode
from picturesq.config.operations import (
    HSL_FULL_CHROMA,
    HUE_BANDS,
    SPLIT_TONE_BALANCE,
    SPLIT_TONE_CHROMA,
    SPLIT_TONE_WIDTH,
    VIBRANCE_FULL_CHROMA,
    ContrastOperation,
    CurvePoint,
    ExposureOperation,
    FadeOperation,
    HslOperation,
    Operation,
    SaturationOperation,
    Space,
    SplitToneOperation,
    ToneCurveOperation,
    VibranceOperation,
    WhiteBalanceOperation,
)

Pixels = Callable[[FloatArray], object]
"""Changes a block of pixels (Nx3) in place."""

_LUMINANCE = REC2020_TO_XYZ[1].astype(np.float32)
MIN_CONTRAST_SLOPE = 0.05
"""Least slope (output stops per input stop) contrast keeps at any intensity: below it,
tones would reverse order."""
_D65_KELVIN, _D65_TINT = xy_to_kelvin_tint(D65)
_MIN_MIRED, _MAX_MIRED = 1.0, mired(1667.0)
"""Range of the light a white balance operation re-balances from (at intensities above 1,
warmth can reach past it)."""


def each_block(image: FloatArray, change: Pixels) -> FloatArray:
    """Run ``change`` on every block of ``image``'s pixels, in place. Returns ``image``."""
    if not image.flags.c_contiguous:
        pixels = image.reshape(-1, 3)
        change(pixels)
        image[...] = pixels.reshape(image.shape)
        return image
    pixels = image.reshape(-1, 3)
    parallel.run(partial(change, pixels[block]) for block in parallel.pixel_blocks(len(pixels)))
    return image


def exposure(image: FloatArray, operation: ExposureOperation) -> FloatArray:
    """Multiply ``image`` by ``2**ev``, in place."""
    gain = np.float32(2.0**operation.ev)
    return each_block(image, lambda pixels: np.multiply(pixels, gain, out=pixels))


def white_balance_operation_matrix(operation: WhiteBalanceOperation) -> np.ndarray:
    """The re-balancing matrix of ``operation``: from a light ``warmth`` mired bluer and
    ``tint`` greener than D65, to D65."""
    reciprocal = np.clip(mired(_D65_KELVIN) - operation.warmth, _MIN_MIRED, _MAX_MIRED)
    kelvin = 1e6 / float(reciprocal)
    source = kelvin_tint_to_xy(kelvin, _D65_TINT - operation.tint)
    return white_balance_matrix(source, D65)


def white_balance(image: FloatArray, operation: WhiteBalanceOperation) -> FloatArray:
    """Warm/cool and tint ``image`` by chromatic adaptation, in place."""
    matrix = white_balance_operation_matrix(operation)
    return each_block(image, lambda pixels: apply_matrix(pixels, matrix, out=pixels))


def contrast(image: FloatArray, operation: ContrastOperation) -> FloatArray:
    """Log-space contrast around ``pivot`` on luminance, same gain on R, G and B, in place."""
    exponent = np.float32(max(operation.amount, MIN_CONTRAST_SLOPE - 1.0))
    pivot = np.float32(operation.pivot)

    def change(pixels: FloatArray) -> None:
        gain = pixels @ _LUMINANCE
        np.maximum(gain, EV_FLOOR, out=gain)
        np.divide(gain, pivot, out=gain)
        np.power(gain, exponent, out=gain)
        np.multiply(pixels, gain[:, None], out=pixels)

    return each_block(image, change)


def saturation(image: FloatArray, operation: SaturationOperation) -> FloatArray:
    """Scale Oklab chroma by ``1 + amount`` (never below 0), in place."""
    factor = np.float32(max(0.0, 1.0 + operation.amount))

    def change(pixels: FloatArray) -> None:
        rec2020_to_oklab(pixels, out=pixels)
        np.multiply(pixels[:, 1:], factor, out=pixels[:, 1:])
        oklab_to_rec2020(pixels, out=pixels)

    return each_block(image, change)


CURVE_STEP_EV = 1.0 / 64.0
"""Spacing of the table a tone curve is evaluated from (the curve is smooth; linear
interpolation between entries this close is within 1e-4 EV of it, measured: 3e-5)."""


TAIL_EV = 40.0
"""How far past its end points a tone curve's straight tails are tabulated (further than
any pixel: luminance is floored at 2^-20, about -17.5 EV)."""


def _curve_slopes(xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Monotone cubic (PCHIP, Fritsch-Carlson) slopes at the points. At the ends, the end
    secant: the curve leaves its last point at the slope it arrived with and continues
    straight, so the tails join without a kink."""
    h = np.diff(xs)
    secant = np.diff(ys) / h
    slopes = np.empty_like(xs)
    for i in range(1, len(xs) - 1):
        before, after = secant[i - 1], secant[i]
        if before * after <= 0.0:
            slopes[i] = 0.0
        else:
            w1, w2 = 2.0 * h[i] + h[i - 1], h[i] + 2.0 * h[i - 1]
            slopes[i] = (w1 + w2) / (w1 / before + w2 / after)
    slopes[0], slopes[-1] = secant[0], secant[-1]
    return slopes


def tone_curve_table(points: tuple[CurvePoint, ...]) -> tuple[np.ndarray, np.ndarray]:
    """``(ev, shift)``: the curve's output minus its input, tabulated over its points and
    out to ``TAIL_EV`` beyond them, where it continues straight at the end secants (a
    curve that softens highlights keeps softening them). ``np.interp`` of the table is the
    curve; one point is a constant shift.
    """
    if len(points) == 1:
        ((x, y),) = points
        return np.array([x]), np.array([y - x])
    xs = np.array([x for x, _ in points], dtype=np.float64)
    ys = np.array([y for _, y in points], dtype=np.float64)
    slopes = _curve_slopes(xs, ys)
    grid = np.arange(xs[0], xs[-1] + CURVE_STEP_EV, CURVE_STEP_EV)
    grid[-1] = xs[-1]
    i = np.clip(np.searchsorted(xs, grid, side="right") - 1, 0, len(xs) - 2)
    h = xs[i + 1] - xs[i]
    t = (grid - xs[i]) / h
    t2, t3 = t * t, t * t * t
    curve = (
        (2 * t3 - 3 * t2 + 1) * ys[i]
        + (t3 - 2 * t2 + t) * h * slopes[i]
        + (-2 * t3 + 3 * t2) * ys[i + 1]
        + (t3 - t2) * h * slopes[i + 1]
    )
    low, high = xs[0] - TAIL_EV, xs[-1] + TAIL_EV
    grid = np.concatenate([[low], grid, [high]])
    curve = np.concatenate([[ys[0] - TAIL_EV * slopes[0]], curve, [ys[-1] + TAIL_EV * slopes[-1]]])
    return grid, curve - grid


def tone_curve(image: FloatArray, operation: ToneCurveOperation) -> FloatArray:
    """Move each pixel's luminance along the curve, the same gain on R, G and B, in place."""
    grid, shift = tone_curve_table(operation.points)
    grid, shift = grid.astype(np.float32), shift.astype(np.float32)
    grey = np.float32(MIDDLE_GREY)

    def change(pixels: FloatArray) -> None:
        gain = pixels @ _LUMINANCE
        np.maximum(gain, EV_FLOOR, out=gain)
        np.divide(gain, grey, out=gain)
        np.log2(gain, out=gain)
        gain = np.interp(gain, grid, shift).astype(np.float32)
        np.exp2(gain, out=gain)
        np.multiply(pixels, gain[:, None], out=pixels)

    return each_block(image, change)


def fade(image: FloatArray, operation: FadeOperation) -> FloatArray:
    """Lift display-referred ``image`` (display-linear, 0 to 1): ``e + amount * (1 - e)``
    on its sRGB-encoded values, in place."""
    lift = np.float32(operation.amount)
    keep = np.float32(1.0 - operation.amount)

    def change(pixels: FloatArray) -> None:
        srgb_encode(pixels, out=pixels)
        np.multiply(pixels, keep, out=pixels)
        np.add(pixels, lift, out=pixels)
        srgb_decode(pixels, out=pixels)

    return each_block(image, change)


def _chroma(lab: FloatArray) -> FloatArray:
    return np.hypot(lab[:, 1], lab[:, 2])


def _smoothstep(low: float, high: float, x: FloatArray) -> FloatArray:
    t = np.clip((x - np.float32(low)) / np.float32(high - low), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def vibrance(image: FloatArray, operation: VibranceOperation) -> FloatArray:
    """Scale Oklab chroma more for muted colours than colourful ones, in place."""
    amount = np.float32(operation.amount)
    full = np.float32(VIBRANCE_FULL_CHROMA)

    def change(pixels: FloatArray) -> None:
        lab = rec2020_to_oklab(pixels, out=pixels)
        factor = _chroma(lab)
        np.divide(factor, full, out=factor)
        np.subtract(1.0, factor, out=factor)
        np.maximum(factor, 0.0, out=factor)
        np.multiply(factor, amount, out=factor)
        np.add(factor, 1.0, out=factor)
        np.maximum(factor, 0.0, out=factor)
        np.multiply(lab[:, 1:], factor[:, None], out=lab[:, 1:])
        oklab_to_rec2020(lab, out=pixels)

    return each_block(image, change)


HUE_TABLE_STEP = 0.25
"""Spacing, in degrees, of the table hue band changes are looked up in."""


def hue_band_table(operation: HslOperation) -> tuple[np.ndarray, np.ndarray]:
    """``(hue, changes)``: each hue's blended (hue shift, chroma change, lightness EV).

    Between two band centres the weights are ``cos²`` and ``sin²`` of the way across, so
    they sum to 1 and change smoothly; the table wraps at 360 degrees.
    """
    centres = np.array(list(HUE_BANDS.values()))
    bands = [getattr(operation, name) for name in HUE_BANDS]
    values = np.array([[band.hue, band.chroma, band.lightness] for band in bands])
    hues = np.arange(0.0, 360.0, HUE_TABLE_STEP)
    after = np.searchsorted(centres, hues, side="right") % len(centres)
    before = (after - 1) % len(centres)
    span = (centres[after] - centres[before]) % 360.0
    t = ((hues - centres[before]) % 360.0) / span
    w_after = np.sin(0.5 * np.pi * t) ** 2
    changes = (1.0 - w_after)[:, None] * values[before] + w_after[:, None] * values[after]
    return hues, changes


def hsl(image: FloatArray, operation: HslOperation) -> FloatArray:
    """Change hue, chroma and brightness by hue band (Oklab), in place."""
    hues, changes = hue_band_table(operation)
    hue_shift, chroma_change, lightness = (changes[:, i].astype(np.float32) for i in range(3))
    has_lightness = bool(np.any(lightness))

    def change(pixels: FloatArray) -> None:
        lab = rec2020_to_oklab(pixels, out=pixels)
        chroma = _chroma(lab)
        hue = np.degrees(np.arctan2(lab[:, 2], lab[:, 1])) % np.float32(360.0)
        weight = _smoothstep(0.0, HSL_FULL_CHROMA, chroma)
        shift = np.interp(hue, hues, hue_shift, period=360.0).astype(np.float32)
        new_hue = np.radians(hue + weight * shift)
        scale = 1.0 + weight * np.interp(hue, hues, chroma_change, period=360.0)
        new_chroma = chroma * np.maximum(scale, 0.0).astype(np.float32)
        lab[:, 1] = new_chroma * np.cos(new_hue)
        lab[:, 2] = new_chroma * np.sin(new_hue)
        oklab_to_rec2020(lab, out=pixels)
        if has_lightness:
            ev = weight * np.interp(hue, hues, lightness, period=360.0).astype(np.float32)
            np.multiply(pixels, np.exp2(ev)[:, None], out=pixels)

    return each_block(image, change)


_GREY_LIGHTNESS = float(np.cbrt(MIDDLE_GREY))
"""Oklab lightness of mid grey (0.565)."""


def split_tone(image: FloatArray, operation: SplitToneOperation) -> FloatArray:
    """Tint shadows and highlights toward their hues in Oklab a/b, in place."""
    crossover = _GREY_LIGHTNESS + SPLIT_TONE_BALANCE * operation.balance
    tints = []
    for tint in (operation.shadows, operation.highlights):
        angle = np.radians(tint.hue)
        size = SPLIT_TONE_CHROMA * tint.amount / _GREY_LIGHTNESS
        tints.append((np.float32(size * np.cos(angle)), np.float32(size * np.sin(angle))))
    (shadow_a, shadow_b), (high_a, high_b) = tints

    def change(pixels: FloatArray) -> None:
        lab = rec2020_to_oklab(pixels, out=pixels)
        lightness = lab[:, 0]
        high = _smoothstep(crossover - SPLIT_TONE_WIDTH, crossover + SPLIT_TONE_WIDTH, lightness)
        # In proportion to lightness, so black stays black; at most as much as at white.
        size = np.clip(lightness, 0.0, 1.0)
        low = (1.0 - high) * size
        high *= size
        lab[:, 1] += low * shadow_a + high * high_a
        lab[:, 2] += low * shadow_b + high * high_b
        oklab_to_rec2020(lab, out=pixels)

    return each_block(image, change)


_FUNCTIONS: dict[type[Operation], Callable[[FloatArray, Any], FloatArray]] = {
    ExposureOperation: exposure,
    WhiteBalanceOperation: white_balance,
    ContrastOperation: contrast,
    SaturationOperation: saturation,
    ToneCurveOperation: tone_curve,
    FadeOperation: fade,
    VibranceOperation: vibrance,
    HslOperation: hsl,
    SplitToneOperation: split_tone,
}


def apply_operation(image: FloatArray, operation: Operation, intensity: float = 1.0) -> FloatArray:
    """Apply ``operation`` at ``intensity`` to ``image``, in place. Returns ``image``.

    Neutral after scaling (intensity 0, or neutral values) means untouched.
    """
    if intensity == 0.0:
        return image
    if intensity != 1.0:
        operation = operation.scaled(intensity)
    if operation.is_neutral():
        return image
    return _FUNCTIONS[type(operation)](image, operation)


def apply_operations(
    image: FloatArray, operations: Iterable[Operation], intensity: float, space: Space
) -> FloatArray:
    """Apply the operations of ``space`` among ``operations``, in order, in place."""
    for operation in operations:
        if operation.space == space:
            image = apply_operation(image, operation, intensity)
    return image
