"""DNG lens corrections stored as opcodes (DNG spec 1.6, chapter 7), read and applied.

A DNG can carry lists of processing steps ("opcodes") the camera maker wants renderers to
run. ``OpcodeList3`` runs on the demosaiced, linear camera RGB image, and is where cameras
put lens corrections. LibRaw ignores it, so we read it here (file IO) and apply the two
lens opcodes ourselves:

- **GainMap** (id 9): a grid of per-plane gains, interpolated bilinearly (vignetting).
- **WarpRectilinear** (id 1): per-plane radial and tangential distortion around an optical
  centre (distortion; per-plane coefficients also correct lateral chromatic aberration).

Other opcodes are reported as unsupported and skipped. Coordinates are relative to the
image, so the same opcodes apply to a half-size decode.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Final

import numpy as np
import tifffile
from numpy.typing import NDArray

from picturesq import parallel

OPCODE_LIST_3_TAG: Final = 51022
WARP_RECTILINEAR: Final = 1
GAIN_MAP: Final = 9


@dataclass(frozen=True)
class GainMap:
    """Per-plane gains on a regular grid, in image-relative coordinates."""

    top: int
    left: int
    bottom: int
    right: int
    plane: int
    planes: int
    origin: tuple[float, float]
    """(vertical, horizontal) relative position of the first grid point."""
    spacing: tuple[float, float]
    gains: NDArray[np.float32]
    """Shape (points_v, points_h, map_planes)."""


@dataclass(frozen=True)
class WarpRectilinear:
    """``coefficients[p] = (kr0, kr1, kr2, kr3, kt0, kt1)`` per plane; ``centre`` = (x, y)."""

    coefficients: NDArray[np.float64]
    centre: tuple[float, float]


Opcode = GainMap | WarpRectilinear


@dataclass(frozen=True)
class LensCorrections:
    opcodes: tuple[Opcode, ...]
    unsupported: tuple[int, ...]
    """Ids of opcodes found but not applied."""

    def __bool__(self) -> bool:
        return bool(self.opcodes)


NO_CORRECTIONS: Final = LensCorrections((), ())


def parse_opcode_list(data: bytes) -> LensCorrections:
    """Parse a DNG opcode list (big-endian, as stored in the tag)."""
    (count,) = struct.unpack_from(">I", data, 0)
    offset = 4
    opcodes: list[Opcode] = []
    unsupported: list[int] = []
    for _ in range(count):
        opcode_id, _version, _flags, size = struct.unpack_from(">IIII", data, offset)
        body = data[offset + 16 : offset + 16 + size]
        offset += 16 + size
        if opcode_id == GAIN_MAP:
            top, left, bottom, right, plane, planes, _rp, _cp, points_v, points_h = (
                struct.unpack_from(">10I", body, 0)
            )
            spacing_v, spacing_h, origin_v, origin_h = struct.unpack_from(">4d", body, 40)
            (map_planes,) = struct.unpack_from(">I", body, 72)
            gains = np.frombuffer(
                body, dtype=">f4", count=points_v * points_h * map_planes, offset=76
            )
            opcodes.append(
                GainMap(
                    top, left, bottom, right, plane, planes,
                    (origin_v, origin_h), (spacing_v, spacing_h),
                    gains.reshape(points_v, points_h, map_planes).astype(np.float32),
                )
            )  # fmt: skip
        elif opcode_id == WARP_RECTILINEAR:
            (planes,) = struct.unpack_from(">I", body, 0)
            values = struct.unpack_from(f">{6 * planes + 2}d", body, 4)
            coefficients = np.array(values[: 6 * planes]).reshape(planes, 6)
            opcodes.append(WarpRectilinear(coefficients, (values[-2], values[-1])))
        else:
            unsupported.append(opcode_id)
    return LensCorrections(tuple(opcodes), tuple(unsupported))


def read_lens_corrections(path: Path) -> LensCorrections:
    """The ``OpcodeList3`` lens corrections of a DNG; none for other files."""
    try:
        with tifffile.TiffFile(path) as tiff:
            pages = list(tiff.pages)
            for page in list(pages):
                pages.extend(getattr(page, "pages", None) or [])
            for page in pages:
                tag = page.tags.get(OPCODE_LIST_3_TAG)  # pyright: ignore[reportAttributeAccessIssue]
                if tag is not None:
                    return parse_opcode_list(bytes(tag.value))
    except (tifffile.TiffFileError, ValueError, IndexError, struct.error):
        return NO_CORRECTIONS
    return NO_CORRECTIONS


def _relative(count: int) -> NDArray[np.float64]:
    """Pixel positions as image-relative coordinates, 0 at the first pixel and 1 at the last."""
    return np.arange(count) / max(1, count - 1)


def gain_at(
    gain_map: GainMap, rel_y: NDArray[np.float64], rel_x: NDArray[np.float64]
) -> NDArray[np.float32]:
    """Bilinearly interpolated gains at relative positions (any equal shapes): (..., map_planes).

    Positions outside the grid take the nearest edge value, as the spec requires.
    """
    points_v, points_h, _ = gain_map.gains.shape
    gy = np.clip((rel_y - gain_map.origin[0]) / gain_map.spacing[0], 0.0, points_v - 1.0)
    gx = np.clip((rel_x - gain_map.origin[1]) / gain_map.spacing[1], 0.0, points_h - 1.0)
    y0 = (
        np.minimum(np.floor(gy).astype(np.intp), points_v - 2)
        if points_v > 1
        else np.zeros_like(gy, np.intp)
    )
    x0 = (
        np.minimum(np.floor(gx).astype(np.intp), points_h - 2)
        if points_h > 1
        else np.zeros_like(gx, np.intp)
    )
    y1, x1 = np.minimum(y0 + 1, points_v - 1), np.minimum(x0 + 1, points_h - 1)
    fy = (gy - y0)[..., None].astype(np.float32)
    fx = (gx - x0)[..., None].astype(np.float32)
    g = gain_map.gains
    top = g[y0, x0] * (1 - fx) + g[y0, x1] * fx
    bottom = g[y1, x0] * (1 - fx) + g[y1, x1] * fx
    return (top * (1 - fy) + bottom * fy).astype(np.float32)


def _plane_gain(
    gain_map: GainMap,
    plane: int,
    ys: NDArray[np.float64],
    xs: NDArray[np.float64],
    height: int,
    width: int,
) -> NDArray[np.float32] | None:
    """The gain for ``plane`` at pixel positions (ys, xs), or None if the map skips the plane.

    Pixels outside the map's area get a gain of 1.
    """
    index = plane - gain_map.plane
    if not 0 <= index < gain_map.planes:
        return None
    gains = gain_at(gain_map, ys / max(1, height - 1), xs / max(1, width - 1))
    gain = gains[..., min(index, gains.shape[-1] - 1)]
    rows, cols = np.rint(ys), np.rint(xs)
    inside = (
        (rows >= gain_map.top) & (rows < gain_map.bottom)
        & (cols >= gain_map.left) & (cols < gain_map.right)
    )  # fmt: skip
    return np.where(inside, gain, np.float32(1.0)).astype(np.float32)


def _warp_sources(
    warp: WarpRectilinear,
    plane: int,
    ys: NDArray[np.float64],
    xs: NDArray[np.float64],
    height: int,
    width: int,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Source pixel coordinates for destination pixels (ys, xs), per the DNG spec."""
    kr0, kr1, kr2, kr3, kt0, kt1 = warp.coefficients[min(plane, len(warp.coefficients) - 1)]
    cx, cy = warp.centre[0] * (width - 1), warp.centre[1] * (height - 1)
    corners = np.array([[0, 0], [width - 1, 0], [0, height - 1], [width - 1, height - 1]], float)
    m = np.hypot(corners[:, 0] - cx, corners[:, 1] - cy).max()
    dx, dy = (xs - cx) / m, (ys - cy) / m
    r2 = dx * dx + dy * dy
    radial = kr0 + r2 * (kr1 + r2 * (kr2 + r2 * kr3))
    src_x = dx * radial + kt0 * 2 * dx * dy + kt1 * (r2 + 2 * dx * dx)
    src_y = dy * radial + kt1 * 2 * dx * dy + kt0 * (r2 + 2 * dy * dy)
    return cy + m * src_y, cx + m * src_x


def _bilinear(
    source: NDArray[np.number], channel: int, sy: NDArray[np.float64], sx: NDArray[np.float64]
) -> NDArray[np.float32]:
    height, width = source.shape[:2]
    sy = np.clip(sy, 0.0, height - 1.0)
    sx = np.clip(sx, 0.0, width - 1.0)
    y0 = np.minimum(np.floor(sy).astype(np.intp), max(0, height - 2))
    x0 = np.minimum(np.floor(sx).astype(np.intp), max(0, width - 2))
    y1, x1 = np.minimum(y0 + 1, height - 1), np.minimum(x0 + 1, width - 1)
    fy, fx = (sy - y0).astype(np.float32), (sx - x0).astype(np.float32)
    plane = source[..., channel]

    def at(y: NDArray[np.intp], x: NDArray[np.intp]) -> NDArray[np.float32]:
        return plane[y, x].astype(np.float32)  # only the gathered pixels are converted

    top = at(y0, x0) * (1 - fx) + at(y0, x1) * fx
    bottom = at(y1, x0) * (1 - fx) + at(y1, x1) * fx
    return (top * (1 - fy) + bottom * fy).astype(np.float32)


def apply_lens_corrections(
    source: NDArray[np.number], corrections: LensCorrections, scale: float
) -> NDArray[np.float32]:
    """Return ``source`` (H x W x 3 camera RGB, any numeric type) x ``scale`` as float32,
    with the opcodes applied in list order.

    Works a block of rows at a time and never holds a second float copy of the image: a
    warp reads from ``source`` (e.g. LibRaw's uint16 output) and writes the result directly.
    Gain maps listed before the warp are evaluated where each pixel came *from*, which is
    the same as applying them first.
    """
    height, width = source.shape[:2]
    warps = [op for op in corrections.opcodes if isinstance(op, WarpRectilinear)]
    warp = warps[0] if warps else None
    warp_index = corrections.opcodes.index(warp) if warp is not None else len(corrections.opcodes)
    before = [op for op in corrections.opcodes[:warp_index] if isinstance(op, GainMap)]
    after = [op for op in corrections.opcodes[warp_index + 1 :] if isinstance(op, GainMap)]
    out = np.empty((height, width, 3), dtype=np.float32)

    def correct_rows(top: int, bottom: int) -> None:
        ys, xs = np.meshgrid(
            np.arange(top, bottom, dtype=np.float64),
            np.arange(width, dtype=np.float64),
            indexing="ij",
        )
        block = out[top:bottom]
        for channel in range(3):
            if warp is None:
                block[..., channel] = source[top:bottom, :, channel]
                sy, sx = ys, xs
            else:
                sy, sx = _warp_sources(warp, channel, ys, xs, height, width)
                block[..., channel] = _bilinear(source, channel, sy, sx)
            for gain_map, (gy, gx) in [(g, (sy, sx)) for g in before] + [
                (g, (ys, xs)) for g in after
            ]:
                gain = _plane_gain(gain_map, channel, gy, gx, height, width)
                if gain is not None:
                    block[..., channel] *= gain
        np.multiply(block, np.float32(scale), out=block)

    parallel.run(partial(correct_rows, *rows) for rows in parallel.row_blocks(height, width))
    return out
