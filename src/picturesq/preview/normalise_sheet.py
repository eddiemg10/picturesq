"""The contact sheet of a normalised project: does the batch look even?

One panel per photo: its proxy after normalise, rendered neutrally (the grade stage, which is
the neutral render until looks arrive in M3, then the display transform), captioned with the
photo's name, exposure and flags. Flagged photos get an amber border and caption. Written by
``picturesq normalise --png``; the layout is the stage sheet's
(:func:`~picturesq.preview.stage_sheet.compose_sheet`).

Pure apart from returning pixels: the caller writes the file.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

import numpy as np
from PIL import Image

from picturesq.colour.transfer import FloatArray
from picturesq.config import OutputConfig, ProjectConfig
from picturesq.export import resize_to_long_edge
from picturesq.grade import grade
from picturesq.photo import PhotoContext
from picturesq.pipeline.export import render_output
from picturesq.pipeline.normalise import NormaliseResult
from picturesq.preview.stage_sheet import Panel, Uint8Array, compose_sheet

PANEL_SIZE: Final = (400, 300)
"""Width and height of each panel's tile; photos are fitted inside it."""
COLUMNS: Final = 4
LABEL_LINES: Final = 2
"""Caption lines: name and exposure; flags."""
WORK_LONG_EDGE: Final = 800
"""The proxy is reduced to this before the grade (cheap, and plenty for a 400 px panel)."""
FLAG_COLOUR: Final = (255, 176, 0)
"""Amber: the border and caption of a flagged (or failed) photo."""
_FAILED_GREY: Final = 64


def render_panel_pixels(
    image: FloatArray, config: ProjectConfig, photo: PhotoContext
) -> Uint8Array:
    """Neutral render of a normalised proxy ``image`` for a panel (8-bit sRGB).

    The grade stage and the display transform, as an export would, through a small view
    output at panel size (as the stage sheet does). ``image`` is not changed.
    """
    small = resize_to_long_edge(image, WORK_LONG_EDGE)
    if small is image:
        small = image.copy()  # the grade works in place
    grade(small, config, photo)
    view = OutputConfig(long_edge=max(PANEL_SIZE))
    return render_output(small, view, config.grade.display_transform, consume=True)


def caption(result: NormaliseResult) -> str:
    """Two lines: name and exposure; the flags (or 'no flags')."""
    if result.error is not None:
        return f"{result.name}\nFAILED"
    if result.exposure is None:
        exposure = "normalise off"
    else:
        source = " (override)" if "exposure_ev" in result.overrides else ""
        exposure = f"{result.exposure.ev:+.2f} EV{source}"
    flags = ", ".join(flag.name for flag in result.flags) or "no flags"
    return f"{result.name} · {exposure}\n{flags}"


def normalise_panel(result: NormaliseResult, pixels: Uint8Array | None) -> Panel:
    """The panel of one photo; ``pixels`` None (a failed photo) gives a grey tile."""
    if pixels is None:
        width, height = PANEL_SIZE
        pixels = np.full((height, width, 3), _FAILED_GREY, dtype=np.uint8)
    marked = result.error is not None or bool(result.flags)
    return Panel(caption(result), pixels, mark=FLAG_COLOUR if marked else None)


def normalise_sheet(title: str, panels: Sequence[Panel]) -> Image.Image:
    """Lay the photos' panels out, :data:`COLUMNS` wide."""
    return compose_sheet(title, panels, PANEL_SIZE, columns=COLUMNS, label_lines=LABEL_LINES)
