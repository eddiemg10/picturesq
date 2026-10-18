"""White balance in normalise: re-balancing a photo to a white given as kelvin and tint.

Pure functions, no IO. The decode keeps the camera's as-shot white balance; a photo's
``wb_kelvin`` / ``tint`` override says the light was a different white, and
:func:`rebalance_white` moves the image from the one to the other.
"""

from functools import partial

import numpy as np

from picturesq import parallel
from picturesq.colour.spaces import apply_matrix
from picturesq.colour.temperature import (
    Matrix,
    kelvin_tint_to_xy,
    white_balance_matrix,
    xy_to_kelvin_tint,
)
from picturesq.colour.transfer import FloatArray
from picturesq.config import NormaliseOverrides

MIN_KELVIN = 1667.0
"""Reddest white :func:`kelvin_tint_to_xy` accepts (the end of Robertson's table)."""


class WhiteBalanceOverrideError(ValueError):
    """A white balance override is set, but the photo's as-shot white is unknown."""


def rebalance_matrix(as_shot_xy: tuple[float, float], target_xy: tuple[float, float]) -> Matrix:
    """Linear Rec.2020 → linear Rec.2020: from an image balanced for ``as_shot_xy`` to the
    same scene balanced for ``target_xy``. Identity when the two are equal.

    The result is ``white_balance_matrix(target_xy, as_shot_xy)``; the derivation, in
    Bradford's cone-like space where every adaptation is a diagonal scaling (``B`` is the
    Bradford matrix, ``cone(w) = B @ XYZ(w)`` with luminance Y = 1, ``A(s → t)`` the
    adaptation ``B⁻¹ diag(cone(t) / cone(s)) B``):

    1. The decode balanced for the as-shot white: a surface with XYZ ``x`` under the light
       ends up at ``A(as_shot → D65) x`` (the working space's white is D65, RGB 1, 1, 1).
    2. Had the camera balanced for the target white instead, it would be at
       ``A(target → D65) x``.
    3. So the image needs ``A(target → D65) A(as_shot → D65)⁻¹``
       ``= B⁻¹ diag(D65 / target) diag(as_shot / D65) B = B⁻¹ diag(as_shot / target) B``,
       which is ``A(target → as_shot)``, wrapped in the working space's matrices.

    Check: a grey lit by the target white decodes to ``A(as_shot → D65) XYZ(target)``;
    the matrix takes it to ``B⁻¹ diag(D65 / target) cone(target) = XYZ(D65)``, neutral.

    Equivalently, find where that grey sits in the decoded image (``xy'``) and adapt it to
    D65 with ``white_balance_matrix(xy', D65)``: the same matrix up to a scalar gain,
    because ``xy`` drops luminance. The composition keeps a target-white surface's
    luminance exactly, so the override changes colour and not exposure.
    """
    return white_balance_matrix(target_xy, as_shot_xy)


def rebalance_white(
    image: FloatArray,
    as_shot_xy: tuple[float, float],
    target_xy: tuple[float, float],
    out: FloatArray | None = None,
) -> FloatArray:
    """Re-balance ``image`` (linear Rec.2020) from ``as_shot_xy`` to ``target_xy``.

    A surface that was neutral under the target white comes out neutral. ``out`` may be
    ``image``. See :func:`rebalance_matrix` for the maths. Works a block of pixels at a time
    on several cores, so the temporary copy stays block-sized.
    """
    out = np.empty_like(image) if out is None else out
    matrix = rebalance_matrix(as_shot_xy, target_xy)
    if not (image.flags.c_contiguous and out.flags.c_contiguous):
        return apply_matrix(image, matrix, out=out)
    source, target = image.reshape(-1, 3), out.reshape(-1, 3)
    parallel.run(
        partial(apply_matrix, source[block], matrix, out=target[block])
        for block in parallel.pixel_blocks(len(source))
    )
    return out


def override_white(
    overrides: NormaliseOverrides, as_shot_xy: tuple[float, float] | None
) -> tuple[float, float] | None:
    """The white a photo's ``wb_kelvin`` / ``tint`` override asks for, as xy.

    ``None`` when neither is set. Either alone keeps the as-shot value of the other.
    Raises WhiteBalanceOverrideError when an override is set but ``as_shot_xy`` is unknown:
    the re-balance starts from the as-shot white, so there is nothing to start from.
    """
    if overrides.wb_kelvin is None and overrides.tint is None:
        return None
    if as_shot_xy is None:
        raise WhiteBalanceOverrideError(
            "a wb_kelvin/tint override is set, but the photo's as-shot white balance is unknown"
        )
    as_shot_kelvin, as_shot_tint = xy_to_kelvin_tint(as_shot_xy)
    kelvin = overrides.wb_kelvin if overrides.wb_kelvin is not None else as_shot_kelvin
    tint = overrides.tint if overrides.tint is not None else as_shot_tint
    return kelvin_tint_to_xy(max(kelvin, MIN_KELVIN), tint)
