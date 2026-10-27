"""The preview contact sheet: every photo through a set of looks (`picturesq preview`).

One row per photo, one column per variant: the neutral render; the photo's current grade
(its look and adjustments from config), when it has one; then each chosen look. A look
column uses the photo's own intensity and parameter values when it is the photo's look,
and 100 % with the look's defaults otherwise; the photo's adjustments apply in every look
column, as they would in an export. Everything renders from the normalised proxy, reduced
first, so a sheet takes seconds.

Pure apart from returning pixels: the caller loads proxies and writes the file.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
from PIL import Image

from picturesq.colour.transfer import FloatArray
from picturesq.config import AdjustmentsConfig, LookChoice, OutputConfig, ProjectConfig
from picturesq.config.look import Look
from picturesq.decode.info import PhotoInfo
from picturesq.export import resize_to_long_edge
from picturesq.grade import grade_with
from picturesq.photo import PhotoContext, ResolvedLook
from picturesq.pipeline.export import render_output
from picturesq.pipeline.looks import resolve_choice
from picturesq.preview.stage_sheet import Panel, Uint8Array, compose_sheet

PANEL_SIZE: Final = (360, 270)
"""Width and height of each panel's tile; photos are fitted inside it."""
LABEL_LINES: Final = 2
"""Caption lines: the photo; the variant."""
WORK_LONG_EDGE: Final = 720
"""The proxy is reduced to this before grading (twice the panel: plenty, and cheap)."""
CURRENT_COLOUR: Final = (120, 200, 255)
"""Border and caption of the photo's current grade."""
_FAILED_GREY: Final = 64


@dataclass(frozen=True)
class Variant:
    """One column: a label, the look (None: no look) and the adjustments it renders with."""

    label: str
    look: ResolvedLook | None
    adjustments: AdjustmentsConfig
    current: bool = False


def _percent(intensity: float) -> str:
    return f"{round(intensity * 100)} %"


def variants(
    config: ProjectConfig, name: str, looks: Sequence[Look], library: Mapping[str, Look]
) -> list[Variant]:
    """The columns of photo ``name``'s row. Raises like ``resolve_choice``."""
    choice = config.photo_look(name)
    adjustments = config.photo_adjustments(name)
    row = [Variant("neutral", None, AdjustmentsConfig())]
    if choice is not None or adjustments != AdjustmentsConfig():
        look = None if choice is None else resolve_choice(choice, dict(library))
        what = "no look" if choice is None else f"{choice.name} {_percent(choice.intensity)}"
        tweaked = " + adjustments" if adjustments != AdjustmentsConfig() else ""
        row.append(Variant(f"current: {what}{tweaked}", look, adjustments, current=True))
    for look in looks:
        own = choice if choice is not None and choice.name == look.key else None
        resolved = resolve_choice(own or LookChoice(name=look.key), dict(library))
        row.append(Variant(f"{look.key} {_percent(resolved.intensity)}", resolved, adjustments))
    return row


def render_variant(
    image: FloatArray,
    config: ProjectConfig,
    name: str,
    info: PhotoInfo | None,
    variant: Variant,
) -> Uint8Array:
    """A normalised proxy ``image`` through ``variant``, at panel size (8-bit sRGB).

    ``image`` is not changed.
    """
    small = resize_to_long_edge(image, WORK_LONG_EDGE)
    small = small.copy() if small is image else small
    photo = PhotoContext(name=name, info=info, look=variant.look)
    grade_with(small, config, photo, variant.adjustments)
    view = OutputConfig(long_edge=max(PANEL_SIZE))
    return render_output(small, view, config.grade.display_transform, photo=photo, consume=True)


def variant_panel(name: str, variant: Variant, pixels: Uint8Array) -> Panel:
    return Panel(
        f"{name}\n{variant.label}", pixels, mark=CURRENT_COLOUR if variant.current else None
    )


def failed_panel(name: str, error: str) -> Panel:
    width, height = PANEL_SIZE
    pixels = np.full((height, width, 3), _FAILED_GREY, dtype=np.uint8)
    return Panel(f"{name}\nFAILED: {error[:40]}", pixels, mark=(255, 176, 0))


def look_sheet(title: str, rows: Sequence[Sequence[Panel]]) -> Image.Image:
    """Lay the rows out, one photo per row (shorter rows are padded with blank tiles)."""
    columns = max((len(row) for row in rows), default=1)
    width, height = PANEL_SIZE
    blank = Panel("", np.zeros((height, width, 3), dtype=np.uint8))
    panels = [panel for row in rows for panel in [*row, *[blank] * (columns - len(row))]]
    return compose_sheet(title, panels, PANEL_SIZE, columns=columns, label_lines=LABEL_LINES)
