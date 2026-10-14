"""Pure helpers for the stage sheet (no file or network IO); the driver is scripts/stage_sheet.py.

A stage sheet is a contact sheet of one CC0 sample after each pipeline stage, beside the camera
JPEG, plus a clipping view and a stats table. It goes in PR descriptions.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import PurePath
from typing import Final

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw, ImageFont

from picturesq.colour.transfer import srgb_decode

Uint8Array = NDArray[np.uint8]

MARKER_START: Final = "<!-- stage-sheet:start -->"
MARKER_END: Final = "<!-- stage-sheet:end -->"
CLIP_LEVEL: Final = 254  # a channel at or above this (of 255) counts as clipped
CLIP_COLOUR: Final = (255, 0, 255)
REC709_LUMA: Final = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

_BACKGROUND: Final = (32, 32, 32)
_TEXT: Final = (235, 235, 235)
_MARGIN: Final = 10
_LABEL_HEIGHT: Final = 28


@dataclass(frozen=True)
class Panel:
    """One tile of the sheet: a label and an 8-bit sRGB image."""

    label: str
    pixels: Uint8Array


@dataclass(frozen=True)
class PanelStats:
    """Numbers shown under the sheet for one panel."""

    label: str
    median_luminance: float  # Rec.709 Y of the display-linear values, 0..1
    clipped_percent: float
    width: int
    height: int


def validate_sample_name(name: str, listed: Sequence[str]) -> str:
    """Return ``name`` if it is a bare file name listed in the samples manifest, else raise.

    The stage sheet is published, so it must only ever render CC0 samples: paths are refused
    outright, even ones that end in a listed name.
    """
    if name != PurePath(name).name or "/" in name or "\\" in name or name in ("", ".", ".."):
        raise ValueError(f"{name!r} is a path; give a sample name from reference/samples.json")
    if name not in listed:
        raise ValueError(f"{name!r} is not listed in reference/samples.json")
    return name


def clipped_mask(pixels: Uint8Array) -> NDArray[np.bool_]:
    """True where any channel is at or above ``CLIP_LEVEL``."""
    return (pixels >= CLIP_LEVEL).any(axis=-1)


def mark_clipped(pixels: Uint8Array) -> Uint8Array:
    """Copy of ``pixels`` with clipped pixels painted magenta."""
    out = pixels.copy()
    out[clipped_mask(pixels)] = CLIP_COLOUR
    return out


def median_luminance(pixels: Uint8Array) -> float:
    """Median Rec.709 Y of the display-linear (sRGB-decoded) values of ``pixels``, 0 to 1."""
    linear = srgb_decode(pixels.astype(np.float32) / np.float32(255.0))
    return float(np.median(linear @ REC709_LUMA))


@dataclass(frozen=True)
class ExposureMatch:
    """Result of ``match_exposure``."""

    ev: float
    achieved: float  # the measured value at ``ev``
    clamped: bool  # the target was outside what [lo, hi] can reach, so ``ev`` is a bound


def match_exposure(
    measure: Callable[[float], float],
    target: float,
    lo: float = -4.0,
    hi: float = 6.0,
    iterations: int = 25,
) -> ExposureMatch:
    """Find the EV offset in [lo, hi] at which ``measure(ev)`` equals ``target``, by bisection.

    ``measure`` must not decrease as EV rises (the median of a brighter render is never lower).
    Bisection rather than a closed form because the display transform is non-linear. A target
    outside ``[measure(lo), measure(hi)]`` returns the nearer bound with ``clamped`` set.
    """
    at_lo, at_hi = measure(lo), measure(hi)
    if target <= at_lo:
        return ExposureMatch(lo, at_lo, clamped=target < at_lo)
    if target >= at_hi:
        return ExposureMatch(hi, at_hi, clamped=target > at_hi)
    for _ in range(iterations):
        mid = (lo + hi) / 2.0
        if measure(mid) < target:
            lo = mid
        else:
            hi = mid
    ev = (lo + hi) / 2.0
    return ExposureMatch(ev, measure(ev), clamped=False)


def panel_stats(panel: Panel) -> PanelStats:
    """Median luminance (of display-linear values), % clipped and size of one panel."""
    height, width = panel.pixels.shape[:2]
    return PanelStats(
        label=panel.label,
        median_luminance=median_luminance(panel.pixels),
        clipped_percent=float(clipped_mask(panel.pixels).mean() * 100.0),
        width=width,
        height=height,
    )


def stats_table(
    stats: Sequence[PanelStats],
    baseline_exposure: float,
    decode_seconds: float,
    match: ExposureMatch | None = None,
) -> str:
    """Markdown table of ``stats`` followed by a BaselineExposure / decode time line.

    With ``match``, a line gives the exposure offset that matched the camera JPEG.
    """
    lines = [
        "| Panel | Median luminance | Clipped | Size |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| {s.label} | {s.median_luminance:.3f} | {s.clipped_percent:.2f} % "
        f"| {s.width}x{s.height} |"
        for s in stats
    ]
    lines.append("")
    lines.append(
        f"BaselineExposure: {baseline_exposure:+.2f} EV · decode: {decode_seconds:.1f} s "
        "· luminance is Rec.709 Y of the display-linear values (0 to 1)"
    )
    if match is not None:
        note = " (clamped at the search limit; target not reachable)" if match.clamped else ""
        lines.append("")
        lines.append(f"Exposure offset to match camera JPEG: {match.ev:+.2f} EV{note}")
    return "\n".join(lines)


def preview_section(image_url: str, caption: str, table: str) -> str:
    """The marked ``## Preview`` section for a PR body."""
    return (
        f"{MARKER_START}\n## Preview\n\n![stage sheet]({image_url})\n\n"
        f"{caption}\n\n{table}\n{MARKER_END}"
    )


def replace_section(body: str, section: str) -> str:
    """Put ``section`` in ``body``: replace the marked block if present, else append it.

    Text outside the markers is untouched, and applying it twice gives the same body.
    """
    start = body.find(MARKER_START)
    end = body.find(MARKER_END, start + 1) if start != -1 else -1
    if start != -1 and end != -1:
        return body[:start] + section + body[end + len(MARKER_END) :]
    stripped = body.rstrip()
    return f"{stripped}\n\n{section}\n" if stripped else f"{section}\n"


def sheet_size(count: int, panel_size: tuple[int, int], columns: int = 3) -> tuple[int, int]:
    """Pixel size of the sheet for ``count`` panels of ``panel_size`` (width, height) each."""
    columns = max(1, min(columns, count))
    rows = -(-count // columns)
    width, height = panel_size
    title_height = _LABEL_HEIGHT + _MARGIN
    return (
        _MARGIN + columns * (width + _MARGIN),
        title_height + rows * (_LABEL_HEIGHT + height + _MARGIN),
    )


def fit_panel(pixels: Uint8Array, size: tuple[int, int]) -> Image.Image:
    """Scale ``pixels`` to fit inside ``size`` (width, height), centred on a dark tile."""
    image = Image.fromarray(pixels)
    image.thumbnail(size, Image.Resampling.LANCZOS)
    tile = Image.new("RGB", size, _BACKGROUND)
    tile.paste(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
    return tile


def compose_sheet(
    title: str,
    panels: Sequence[Panel],
    panel_size: tuple[int, int] = (500, 375),
    columns: int = 3,
) -> Image.Image:
    """Lay ``panels`` out in a grid (at most ``columns`` wide) under a title line."""
    width, height = panel_size
    columns = max(1, min(columns, len(panels)))
    sheet = Image.new("RGB", sheet_size(len(panels), panel_size, columns), _BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    draw.text((_MARGIN, _MARGIN // 2), title, fill=_TEXT, font=ImageFont.load_default(size=18))
    top = _LABEL_HEIGHT + _MARGIN
    label_font = ImageFont.load_default(size=16)
    for index, panel in enumerate(panels):
        row, column = divmod(index, columns)
        x = _MARGIN + column * (width + _MARGIN)
        y = top + row * (_LABEL_HEIGHT + height + _MARGIN)
        draw.text((x, y + 4), panel.label, fill=_TEXT, font=label_font)
        sheet.paste(fit_panel(panel.pixels, panel_size), (x, y + _LABEL_HEIGHT))
    return sheet
