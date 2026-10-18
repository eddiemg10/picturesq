"""Compare picturesq's real export with the camera's own JPEG, photo by photo (ADR-0010 gate).

For each original: decode, run every stage, render the web output (exactly what
`picturesq export` writes), and compare it with the JPEG embedded in the original:
brightness (EV), chroma per band of the camera's lightness at the same pixels (ADR-0013;
ratio ours / camera's, and the difference ours minus camera's), and clipped highlights.
Prints a table and the gate verdict, and writes one contact sheet (camera | ours per photo).

By default it runs on the CC0 samples (reference/samples/). ``--reference`` runs on the
private reference set (reference/raw/) and writes under reference/.picturesq/, which is
git-ignored: those results are for local review only and must never be committed or posted.

Usage:
    uv run python scripts/compare.py [--out PATH] [--fast]
    uv run python scripts/compare.py --reference [--fast]
"""

from __future__ import annotations

import argparse
import itertools
import sys
from pathlib import Path

import numpy as np

from picturesq import __version__, parallel
from picturesq.config import OutputConfig, ProjectConfig
from picturesq.decode import DecodeError, decode_original, find_originals
from picturesq.decode.embedded import camera_jpeg
from picturesq.pipeline.export import render_output, render_scene
from picturesq.preview.compare import (
    CHROMA_ABS_TOLERANCE,
    CHROMA_RATIO_RANGE,
    LIGHTNESS_BANDS,
    MAX_EXTRA_CLIPPED,
    MAX_MEDIAN_EV,
    PhotoComparison,
    compare_photo,
    gate,
    pooled_ratio,
)
from picturesq.preview.stage_sheet import Panel, compose_sheet

ROOT = Path(__file__).resolve().parent.parent
PANEL_WIDTH = 480


def table(photos: list[PhotoComparison]) -> str:
    bands = [f"{a:.2f}-{b:.2f}" for a, b in itertools.pairwise(LIGHTNESS_BANDS)]
    head = ["photo", "ΔEV", "clipped (cam)", *[f"chroma L {b} ratio (diff)" for b in bands]]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for p in photos:
        differences = [a - b for a, b in zip(p.chroma, p.camera_chroma, strict=True)]
        ratios = [
            "-" if np.isnan(r) or np.isnan(d) else f"{r:.2f} ({d:+.3f})"
            for r, d in zip(p.chroma_ratio, differences, strict=True)
        ]
        lines.append(
            f"| {p.name} | {p.ev_difference:+.2f} | {p.clipped:.2%} ({p.camera_clipped:.2%}) | "
            + " | ".join(ratios)
            + " |"
        )
    return "\n".join(lines)


def main() -> int:
    parallel.use(parallel.auto())
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--reference", action="store_true", help="use the private reference set")
    parser.add_argument("--fast", action="store_true", help="half-size decode (proxy quality)")
    parser.add_argument("--out", type=Path, help="contact sheet path (.jpg)")
    args = parser.parse_args()

    folder = ROOT / "reference" / ("raw" if args.reference else "samples")
    default_out = (
        ROOT / "reference" / ".picturesq" / "compare.jpg"
        if args.reference
        else ROOT / ".picturesq" / "compare.jpg"
    )
    out: Path = args.out or default_out
    originals = find_originals(folder)
    if not originals:
        print(f"error: no originals in {folder}", file=sys.stderr)
        return 1

    config = ProjectConfig()
    web: OutputConfig = config.export.outputs["web"]
    photos: list[PhotoComparison] = []
    panels: list[Panel] = []
    for original in originals:
        jpeg = camera_jpeg(original)
        if jpeg is None:
            print(f"skip {original.name}: no embedded JPEG")
            continue
        try:
            scene = render_scene(
                decode_original(original, config.decode, half_size=args.fast), config
            )
        except DecodeError as error:
            print(f"skip {original.name}: {error}")
            continue
        ours = render_output(scene, web, config.grade.display_transform)
        del scene
        result = compare_photo(original.name, ours, jpeg)
        photos.append(result)
        panels.append(Panel(f"{original.name}: camera JPEG", jpeg))
        panels.append(Panel(f"picturesq export ({result.ev_difference:+.2f} EV)", ours))
        note = "" if result.same_frame else " (embedded JPEG is a different frame: not gated)"
        print(f"{original.name}: {result.ev_difference:+.2f} EV{note}", flush=True)

    if not photos:
        print("error: no photo had an embedded JPEG", file=sys.stderr)
        return 1
    verdict = gate(photos)
    print()
    print(table(photos))
    print()
    low, high = CHROMA_RATIO_RANGE
    print(
        f"brightness: median |ΔEV| {verdict.median_abs_ev:.2f} (≤ {MAX_MEDIAN_EV}) "
        f"{'PASS' if verdict.brightness_ok else 'FAIL'}"
    )
    bands = " ".join("-" if np.isnan(r) else f"{r:.2f}" for r in verdict.band_chroma_ratio)
    differences = " ".join(
        "-" if np.isnan(d) else f"{d:+.3f}" for d in verdict.band_chroma_difference
    )
    colour = "PASS" if verdict.colour_ok else "FAIL"
    print(
        f"colour: chroma ratio per band {bands} (each {low} to {high}), "
        f"difference {differences} (or within ±{CHROMA_ABS_TOLERANCE}) {colour}"
    )
    tolerated = [
        f"L {a:.2f}-{b:.2f}"
        for (a, b), on in zip(
            itertools.pairwise(LIGHTNESS_BANDS), verdict.band_on_tolerance, strict=True
        )
        if on
    ]
    if tolerated:
        print(f"  passed on the absolute difference: {', '.join(tolerated)}")
    gated = [p for p in photos if p.same_frame]
    own = pooled_ratio(
        [p.own_band_chroma for p in gated], [p.camera_own_band_chroma for p in gated]
    )
    own_bands = " ".join("-" if np.isnan(r) else f"{r:.2f}" for r in own)
    print(f"  (each image banded by its own lightness, not gated: {own_bands})")
    print(
        f"highlights: clipped more than camera + {MAX_EXTRA_CLIPPED:.1%}: "
        f"{', '.join(verdict.over_clipped) or 'none'} {'PASS' if verdict.highlights_ok else 'FAIL'}"
    )
    print(f"gate: {'PASS' if verdict.passed else 'FAIL'}")

    out.parent.mkdir(parents=True, exist_ok=True)
    title = f"picturesq {__version__} vs camera JPEG · {len(photos)} photos · default config"
    compose_sheet(title, panels, (PANEL_WIDTH, PANEL_WIDTH * 3 // 4), columns=2).save(
        out, quality=90
    )
    print(f"sheet: {out}")
    return 0 if verdict.passed else 1


if __name__ == "__main__":
    sys.exit(main())
