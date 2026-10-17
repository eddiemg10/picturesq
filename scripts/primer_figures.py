"""Render the figures for the M1 primer (docs/primers/m1-neutral-render.md).

Three small JPEGs from the CC0 DJI sample and synthetic ramps, written to docs/primers/images/:

- ``m1-bayer-mosaic.jpg``: a tiny crop of the raw Bayer mosaic (one number per photosite, the
  filter colour each sits under) beside the same crop after demosaicing.
- ``m1-display-transforms.jpg``: the same scene-linear image shown four ways: the camera JPEG,
  scene-linear values sent straight to the screen, the plain sRGB curve with clipping, and the
  AgX display transform.
- ``m1-ramps.jpg``: grey, blue and orange exposure ramps (-8 to +6 EV) through the plain sRGB
  curve with clipping and through the AgX display transform.

Usage:
    uv run python scripts/primer_figures.py [--out-dir docs/primers/images]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw, ImageFont

from picturesq.colour.display import display_transform
from picturesq.colour.spaces import REC709_TO_REC2020, REC2020_TO_REC709, apply_matrix
from picturesq.colour.transfer import srgb_encode
from picturesq.config import DecodeConfig, ProjectConfig
from picturesq.decode import decode_original, read_baseline_exposure
from picturesq.decode.embedded import camera_jpeg
from picturesq.export import resize_to_long_edge
from picturesq.normalise import normalise

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = "dji-fc4382.dng"
PANEL = (480, 360)
MARGIN = 12
LABEL_HEIGHT = 26
BACKGROUND = (250, 250, 250)
TEXT = (30, 30, 30)
MUTED = (110, 110, 110)
QUALITY = 82

# Raw crop for the mosaic figure: (top, left) in raw pixels, and its size. The castle's teal
# roof edge above a window, where demosaicing has real work to do.
CROP_TOP, CROP_LEFT, CROP_SIZE = 1220, 1294, 32
CELL = 9  # screen pixels per photosite in the enlarged crop

RAMP_EV = (-8.0, 6.0)
RAMP_SIZE = (720, 40)
# Scene-linear Rec.709 colours at mid-grey luminance, before exposure (a sky blue, an orange).
RAMP_COLOURS = {
    "grey": (0.18, 0.18, 0.18),
    "blue": (0.06, 0.17, 0.42),
    "orange": (0.50, 0.14, 0.03),
}

FloatImage = NDArray[np.float32]
Pixels = NDArray[np.uint8]


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


def quantise(display: FloatImage) -> Pixels:
    """Display-encoded values in [0, 1] (anything outside is clipped) to 8-bit."""
    return np.rint(np.clip(display, 0.0, 1.0) * 255.0).astype(np.uint8)


def linear_clipped(scene: FloatImage) -> Pixels:
    """Scene-linear values sent to the screen as they are: no curve, clipped at 1."""
    return quantise(apply_matrix(scene, REC2020_TO_REC709))


def srgb_clipped(scene: FloatImage) -> Pixels:
    """The plain sRGB curve: convert to Rec.709, clip each channel to [0, 1], encode."""
    display = np.clip(apply_matrix(scene, REC2020_TO_REC709), 0.0, 1.0)
    return quantise(srgb_encode(display))


def agx_display(scene: FloatImage) -> Pixels:
    """picturesq's AgX display transform with default settings, then the sRGB curve."""
    return quantise(srgb_encode(display_transform(scene.copy())))


def fit(pixels: Pixels, size: tuple[int, int]) -> Image.Image:
    """Letterbox ``pixels`` into ``size`` without upscaling past it."""
    image = Image.fromarray(pixels)
    image.thumbnail(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", size, BACKGROUND)
    canvas.paste(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
    return canvas


def grid(
    panels: list[tuple[str, Image.Image]], columns: int, caption: str | None = None
) -> Image.Image:
    """Panels of equal size in a grid, each with a label above it, and an optional caption."""
    width, height = panels[0][1].size
    rows = -(-len(panels) // columns)
    caption_height = 24 if caption else 0
    sheet = Image.new(
        "RGB",
        (
            columns * (width + MARGIN) + MARGIN,
            rows * (height + LABEL_HEIGHT + MARGIN) + MARGIN + caption_height,
        ),
        BACKGROUND,
    )
    draw = ImageDraw.Draw(sheet)
    for index, (label, image) in enumerate(panels):
        x = MARGIN + (index % columns) * (width + MARGIN)
        y = MARGIN + (index // columns) * (height + LABEL_HEIGHT + MARGIN)
        draw.text((x, y), label, fill=TEXT, font=font(15))
        sheet.paste(image, (x, y + LABEL_HEIGHT))
    if caption:
        draw.text((MARGIN, sheet.height - caption_height), caption, fill=MUTED, font=font(12))
    return sheet


def scene_for_display(sample: Path) -> FloatImage:
    """The sample decoded (half size, like a proxy), shrunk to panel size, then normalised.

    Normalise applies the camera-fitted exposure offset, so all display panels start from the
    same scene-linear image the grade stage would receive.
    """
    config = ProjectConfig()
    image = decode_original(sample, config.decode, half_size=True)
    image = resize_to_long_edge(image, PANEL[0]).copy()
    return normalise(image, config)


def display_figure(sample: Path) -> Image.Image:
    scene = scene_for_display(sample)
    jpeg = camera_jpeg(sample)
    panels = [
        ("1  scene-linear sent to the screen, clipped", fit(linear_clipped(scene), PANEL)),
        ("2  plain sRGB curve, clipped", fit(srgb_clipped(scene), PANEL)),
        ("3  AgX display transform (picturesq)", fit(agx_display(scene), PANEL)),
    ]
    if jpeg is not None:
        panels.append(("4  camera JPEG (embedded in the DNG)", fit(jpeg, PANEL)))
    caption = (
        "Panels 1-3: the same scene-linear image (decode + normalise); only the display step "
        "differs. Sample: DJI FC4382, raw.pixls.us, CC0."
    )
    return grid(panels, columns=2, caption=caption)


def mosaic_figure(sample: Path) -> Image.Image:
    """Grey mosaic, coloured mosaic and demosaiced crop of the same few hundred photosites."""
    import rawpy  # only this figure reads the raw mosaic itself

    config = ProjectConfig()
    rows = slice(CROP_TOP, CROP_TOP + CROP_SIZE)
    columns = slice(CROP_LEFT, CROP_LEFT + CROP_SIZE)
    with rawpy.imread(str(sample)) as raw:
        values = raw.raw_image_visible[rows, columns].astype(np.float32)
        filters = raw.raw_colors_visible[rows, columns]  # 0 R, 1 G, 2 B, 3 second G
        black = float(np.mean(raw.black_level_per_channel))
        white = float(raw.white_level)
        gains = np.asarray(raw.camera_whitebalance[:3], dtype=np.float32)

    # The same brightening the pipeline applies (BaselineExposure + normalise's exposure
    # offset), so the three panels are comparable.
    ev = read_baseline_exposure(sample) + config.normalise.exposure.offset_ev
    level = np.clip((values - black) / (white - black), 0.0, None) * np.float32(2.0**ev)
    filters = np.where(filters == 3, 1, filters)
    grey = quantise(srgb_encode(np.repeat(level[..., None], 3, axis=2)))
    coloured = np.zeros((*level.shape, 3), dtype=np.float32)
    for channel in range(3):
        mask = filters == channel
        coloured[..., channel][mask] = level[mask] * gains[channel] / gains[1]
    coloured_pixels = quantise(srgb_encode(coloured))

    # Demosaiced by LibRaw (the default AHD), uncropped so raw and output coordinates agree.
    decode = DecodeConfig(default_crop=False)
    full = decode_original(sample, decode)
    demosaiced = full[rows, columns].copy()
    del full
    normalise(demosaiced, config)
    shown = agx_display(demosaiced)

    def enlarge(pixels: Pixels) -> Image.Image:
        size = (CROP_SIZE * CELL, CROP_SIZE * CELL)
        return Image.fromarray(pixels).resize(size, Image.Resampling.NEAREST)

    panels = [
        ("what the sensor stores", enlarge(grey)),
        ("the filter over each photosite", enlarge(coloured_pixels)),
        ("after demosaicing", enlarge(shown)),
    ]
    caption = f"A {CROP_SIZE}x{CROP_SIZE} photosite crop. Sample: DJI FC4382, raw.pixls.us, CC0."
    return grid(panels, columns=3, caption=caption)


def ramp(colour: tuple[float, float, float]) -> FloatImage:
    """A horizontal exposure ramp of one Rec.709 colour, as scene-linear Rec.2020."""
    width, height = RAMP_SIZE
    ev = np.linspace(*RAMP_EV, width, dtype=np.float32)
    rec709 = np.asarray(colour, dtype=np.float32)[None, :] * (2.0**ev)[:, None]
    rec2020 = apply_matrix(rec709.astype(np.float32), REC709_TO_REC2020)
    return np.ascontiguousarray(np.broadcast_to(rec2020, (height, width, 3)), dtype=np.float32)


def ramp_figure() -> Image.Image:
    width, height = RAMP_SIZE
    label_width = 150
    gap = 6
    strips: list[tuple[str, Pixels]] = []
    for name, colour in RAMP_COLOURS.items():
        scene = ramp(colour)
        strips.append((f"{name}: sRGB, clipped", srgb_clipped(scene)))
        strips.append((f"{name}: AgX", agx_display(scene)))
    axis_height = 34
    sheet = Image.new(
        "RGB",
        (label_width + width + 2 * MARGIN, MARGIN + len(strips) * (height + gap) + axis_height),
        BACKGROUND,
    )
    draw = ImageDraw.Draw(sheet)
    x0 = label_width + MARGIN
    for index, (label, pixels) in enumerate(strips):
        y = MARGIN + index * (height + gap) + (gap * (index // 2))
        draw.text((MARGIN, y + height // 2 - 8), label, fill=TEXT, font=font(14))
        sheet.paste(Image.fromarray(pixels), (x0, y))
    low, high = RAMP_EV
    axis_y = sheet.height - axis_height + 4
    for ev in range(int(low), int(high) + 1, 2):
        x = x0 + round((ev - low) / (high - low) * (width - 1))
        draw.line([(x, axis_y), (x, axis_y + 5)], fill=MUTED)
        draw.text((x - 8, axis_y + 7), f"{ev:+d}" if ev else "0", fill=MUTED, font=font(12))
    draw.text((MARGIN, axis_y + 7), "EV (0 = mid grey)", fill=MUTED, font=font(12))
    return sheet


def check_sample(path: Path) -> None:
    manifest = json.loads((ROOT / "reference" / "samples.json").read_text())
    entry = next(s for s in manifest["samples"] if s["name"] == SAMPLE)
    if not path.is_file():
        raise SystemExit(f"error: {path} not found; run scripts/fetch_samples.py")
    if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
        raise SystemExit(f"error: {path} does not match the checksum in samples.json")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out-dir", type=Path, default=ROOT / "docs" / "primers" / "images")
    args = parser.parse_args()
    samples_dir = Path(os.environ.get("PICTURESQ_SAMPLES", ROOT / "reference" / "samples"))
    sample = samples_dir / SAMPLE
    check_sample(sample)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    figures = {
        "m1-bayer-mosaic.jpg": mosaic_figure(sample),
        "m1-display-transforms.jpg": display_figure(sample),
        "m1-ramps.jpg": ramp_figure(),
    }
    for name, figure in figures.items():
        path = args.out_dir / name
        # Fixed settings and no EXIF, so re-running gives the same bytes.
        figure.save(path, quality=QUALITY, optimize=True, progressive=False)
        print(f"wrote {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}", end="")
        print(f" ({figure.width}x{figure.height}, {path.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
