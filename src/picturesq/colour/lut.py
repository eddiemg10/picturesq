"""LUTs: reading ``.cube`` text and applying 1D and 3D tables (plan D8). Pure, no IO.

A 3D LUT stores, for an NxNxN grid of input colours spanning its domain, the output colour.
Colours between grid points are interpolated **tetrahedrally**: the grid cube around the
colour is split into six tetrahedra along its grey diagonal, and the colour is a weighted
sum of the four corners of the one it falls in. Unlike trilinear interpolation (all eight
corners), a grey input only ever uses corners on the grey diagonal, so a LUT that keeps
greys neutral keeps them neutral between grid points too.

``.cube`` (Adobe/Resolve): ``TITLE``, ``LUT_1D_SIZE`` or ``LUT_3D_SIZE``,
``DOMAIN_MIN``/``DOMAIN_MAX`` and one ``r g b`` line per entry, red changing fastest.
"""

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from picturesq.colour.transfer import FloatArray

MAX_3D_SIZE = 65
"""Largest 3D LUT accepted (65^3 entries are 3.3 MB as float32)."""
MAX_1D_SIZE = 65536


class CubeError(ValueError):
    """A ``.cube`` file is malformed; the message names the line."""


@dataclass(frozen=True, eq=False)
class Lut:
    """A parsed LUT. ``table`` is (N, 3) for 1D, or (N, N, N, 3) indexed ``[b, g, r]``."""

    table: NDArray[np.float32]
    domain_min: NDArray[np.float32] = field(default_factory=lambda: np.zeros(3, np.float32))
    domain_max: NDArray[np.float32] = field(default_factory=lambda: np.ones(3, np.float32))
    title: str = ""

    @property
    def is_3d(self) -> bool:
        return self.table.ndim == 4

    @property
    def size(self) -> int:
        return int(self.table.shape[0])


def parse_cube(text: str) -> Lut:
    """Parse ``.cube`` text. Raises CubeError with the line number of the first problem."""
    title, size, dimensions = "", 0, 0
    domain_min, domain_max = np.zeros(3), np.ones(3)
    rows: list[list[float]] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        keyword, _, rest = line.partition(" ")
        rest = rest.strip()
        try:
            if keyword == "TITLE":
                title = rest.strip('"')
            elif keyword in ("LUT_1D_SIZE", "LUT_3D_SIZE"):
                if dimensions:
                    raise CubeError("more than one LUT size")
                dimensions = 1 if keyword == "LUT_1D_SIZE" else 3
                size = int(rest)
                limit = MAX_1D_SIZE if dimensions == 1 else MAX_3D_SIZE
                if not 2 <= size <= limit:
                    raise CubeError(f"{keyword} must be 2 to {limit}, got {size}")
            elif keyword == "DOMAIN_MIN":
                domain_min = np.array([float(v) for v in rest.split()])
            elif keyword == "DOMAIN_MAX":
                domain_max = np.array([float(v) for v in rest.split()])
            elif keyword in ("LUT_1D_INPUT_RANGE", "LUT_3D_INPUT_RANGE"):
                low, high = (float(v) for v in rest.split())
                domain_min, domain_max = np.full(3, low), np.full(3, high)
            elif keyword[0].isdigit() or keyword[0] in "-+.":
                values = [float(v) for v in line.split()]
                if len(values) != 3:
                    raise CubeError(f"expected 3 numbers, got {len(values)}")
                rows.append(values)
            else:
                raise CubeError(f"unknown keyword {keyword!r}")
        except CubeError as error:
            raise CubeError(f"line {number}: {error}") from None
        except ValueError:
            raise CubeError(f"line {number}: cannot read {line!r}") from None
    if not dimensions:
        raise CubeError("no LUT_1D_SIZE or LUT_3D_SIZE")
    if domain_min.shape != (3,) or domain_max.shape != (3,) or (domain_max <= domain_min).any():
        raise CubeError("DOMAIN_MIN and DOMAIN_MAX need 3 numbers each, min below max")
    expected = size if dimensions == 1 else size**3
    if len(rows) != expected:
        raise CubeError(f"expected {expected} entries for size {size}, got {len(rows)}")
    table = np.array(rows, dtype=np.float32)
    if dimensions == 3:
        table = table.reshape(size, size, size, 3)  # red fastest: [b, g, r]
    return Lut(table, domain_min.astype(np.float32), domain_max.astype(np.float32), title)


def _grid_coordinates(pixels: FloatArray, lut: Lut) -> FloatArray:
    scale = (lut.size - 1) / (lut.domain_max - lut.domain_min)
    coordinates = (pixels - lut.domain_min) * scale.astype(np.float32)
    return np.clip(coordinates, 0.0, lut.size - 1, out=coordinates)


def apply_lut_1d(pixels: FloatArray, lut: Lut, out: FloatArray | None = None) -> FloatArray:
    """Each channel through its column of a 1D LUT (linear interpolation, clamped)."""
    coordinates = _grid_coordinates(pixels, lut)
    out = np.empty_like(pixels) if out is None else out
    grid = np.arange(lut.size, dtype=np.float32)
    for channel in range(3):
        out[..., channel] = np.interp(coordinates[..., channel], grid, lut.table[:, channel])
    return out


def apply_lut_3d(pixels: FloatArray, lut: Lut, out: FloatArray | None = None) -> FloatArray:
    """Pixels (N, 3) through a 3D LUT, tetrahedral interpolation, clamped to its domain.

    With the fractions inside the grid cube sorted ``f1 >= f2 >= f3`` along axes
    ``a1, a2, a3``, the result is ``(1 - f1) c000 + (f1 - f2) c[a1] + (f2 - f3) c[a1 + a2]
    + f3 c111``: the six tetrahedra in one formula. ``out`` may be ``pixels``.
    """
    n = lut.size
    flat = lut.table.reshape(-1, 3)
    coordinates = _grid_coordinates(pixels, lut)
    base = np.minimum(coordinates.astype(np.intp), n - 2)
    fraction = (coordinates - base).astype(np.float32)
    # Flat index steps of one grid step along r, g, b (table is [b, g, r]).
    strides = np.array([1, n, n * n], dtype=np.intp)
    corner = base @ strides
    order = np.argsort(-fraction, axis=1, kind="stable")
    sorted_fraction = np.take_along_axis(fraction, order, axis=1)
    steps = strides[order]
    first = corner + steps[:, 0]
    second = first + steps[:, 1]
    last = corner + strides.sum()
    f1, f2, f3 = (sorted_fraction[:, i : i + 1] for i in range(3))
    result = (1.0 - f1) * flat[corner] + (f1 - f2) * flat[first]
    result += (f2 - f3) * flat[second] + f3 * flat[last]
    if out is None:
        return result
    out[...] = result
    return out


def apply_lut(pixels: FloatArray, lut: Lut, out: FloatArray | None = None) -> FloatArray:
    """Pixels (N, 3) through ``lut`` (1D or 3D)."""
    return apply_lut_3d(pixels, lut, out) if lut.is_3d else apply_lut_1d(pixels, lut, out)
