"""Render the figures for the primers in docs/primers/.

Small JPEGs from CC0 samples only (reference/samples/, never the private reference set) and
synthetic data, written to docs/primers/images/.

M1 (m1-neutral-render.md), from the DJI sample and synthetic ramps:

- ``m1-bayer-mosaic.jpg``: a tiny crop of the raw Bayer mosaic (one number per photosite, the
  filter colour each sits under) beside the same crop after demosaicing.
- ``m1-display-transforms.jpg``: the same scene-linear image shown four ways: the camera JPEG,
  scene-linear values sent straight to the screen, the plain sRGB curve with clipping, and the
  AgX display transform.
- ``m1-ramps.jpg``: grey, blue and orange exposure ramps (-8 to +6 EV) through the plain sRGB
  curve with clipping and through the AgX display transform.

M2 (m2-normalise.md), from half-size decodes (to keep memory low):

- ``m2-histogram.jpg``: the DJI sample beside its luminance histogram in EV, with the
  percentiles and the mean marked.
- ``m2-white-balance.jpg``: the Pentax K-5 II s tungsten sample with its as-shot white balance,
  re-balanced by grey-world, and the camera JPEG; below, a kelvin scale in equal kelvin steps
  and in equal mired steps.
- ``m2-noise.jpg``: a crop of the Sony FX3 ISO 20000 sample split into luma and chroma noise,
  after chroma and luma noise reduction, and the whole photo at output size.

Usage:
    uv run python scripts/primer_figures.py [--out-dir docs/primers/images] [--only m1|m2|m3]
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
from picturesq.colour.filters import gaussian_blur
from picturesq.colour.spaces import (
    D65,
    REC709_TO_REC2020,
    REC2020_TO_REC709,
    REC2020_TO_XYZ,
    XYZ_TO_REC709,
    XYZ_TO_REC2020,
    apply_matrix,
)
from picturesq.colour.temperature import bradford_matrix, xy_to_cct, xy_to_xyz, xyz_to_xy
from picturesq.colour.transfer import MIDDLE_GREY, linear_to_ev, srgb_encode
from picturesq.config import DecodeConfig, ProjectConfig
from picturesq.decode import decode_original, read_baseline_exposure
from picturesq.decode.dng_colour import dng_camera_to_working, read_dng_colour
from picturesq.decode.embedded import camera_jpeg
from picturesq.export import resize_to_long_edge
from picturesq.normalise import apply_exposure, chroma_noise_reduction, exposure_ev, normalise

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = "dji-fc4382.dng"
WB_SAMPLE = "pentax-k5iis.dng"
NOISE_SAMPLE = "sony-ilme-fx3.arw"
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

# M2: histogram range and bin width (EV relative to mid grey), the white-balance scale, and the
# noise crop (top, left, height, width in half-size pixels: a cable, a dark card, a box edge).
HISTOGRAM_EV = (-10.0, 6.0)
HISTOGRAM_BIN_EV = 0.25
SCALE_KELVIN = (2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000, 10000)
SCALE_MIRED = (500, 450, 400, 350, 300, 250, 200, 150, 100)
NOISE_CROP = (600, 480, 120, 160)
NOISE_ZOOM = 2
NOISE_PANEL = (NOISE_CROP[3] * NOISE_ZOOM, NOISE_CROP[2] * NOISE_ZOOM)
NOISE_BRIGHTEN_EV = 1.5  # the crops only, so the noise is visible on a dim screen
LUMA_NR_SIGMA = 1.5
ACCENT = (200, 90, 20)

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


# --- M2: normalise ----------------------------------------------------------------------------


def luminance(image: FloatImage) -> FloatImage:
    """Relative luminance Y of linear Rec.2020 pixels."""
    return image @ REC2020_TO_XYZ[1].astype(np.float32)


def vstack(images: list[Image.Image]) -> Image.Image:
    """Images one above the other, left-aligned, on the background colour."""
    size = (max(i.width for i in images), sum(i.height for i in images))
    sheet = Image.new("RGB", size, BACKGROUND)
    y = 0
    for image in images:
        sheet.paste(image, (0, y))
        y += image.height
    return sheet


def histogram_panel(ev: FloatImage, marks: dict[str, float], mean_ev: float) -> Image.Image:
    """A luminance histogram in EV with percentile lines (dark) and the mean (accent)."""
    width, height = PANEL
    left, right, top, bottom = 24, 14, 40, 44
    low, high = HISTOGRAM_EV
    bins = np.arange(low, high + HISTOGRAM_BIN_EV, HISTOGRAM_BIN_EV)
    counts, _ = np.histogram(np.clip(ev, low, high - 1e-3), bins=bins)
    panel = Image.new("RGB", PANEL, BACKGROUND)
    draw = ImageDraw.Draw(panel)
    plot_w, plot_h = width - left - right, height - top - bottom

    def x_of(value: float) -> int:
        return left + round((value - low) / (high - low) * plot_w)

    peak = float(counts.max())
    for index, count in enumerate(counts):
        x0, x1 = x_of(float(bins[index])), x_of(float(bins[index + 1])) - 1
        bar = round(float(count) / peak * plot_h)
        draw.rectangle([(x0, top + plot_h - bar), (x1, top + plot_h)], fill=(170, 170, 170))
    for tick in range(int(low), int(high) + 1, 2):
        x = x_of(tick)
        draw.line([(x, top + plot_h), (x, top + plot_h + 5)], fill=MUTED)
        label = f"{tick:+d}" if tick else "0"
        draw.text((x - 8, top + plot_h + 8), label, fill=MUTED, font=font(12))
    draw.text((left, height - 18), "luminance, EV (0 = mid grey)", fill=MUTED, font=font(12))
    for index, (name, value) in enumerate(marks.items()):
        x = x_of(value)
        draw.line([(x, top - 4), (x, top + plot_h)], fill=TEXT, width=2 if name == "p50" else 1)
        draw.text((x - 10, 4 + 16 * (index % 2)), name, fill=TEXT, font=font(12))
    x = x_of(mean_ev)
    for y in range(top - 4, top + plot_h, 8):
        draw.line([(x, y), (x, y + 4)], fill=ACCENT, width=2)
    draw.text((x + 5, top + 6), "mean", fill=ACCENT, font=font(12))
    return panel


def histogram_figure(sample: Path) -> tuple[Image.Image, dict[str, float]]:
    """The photo and its luminance histogram in EV, and the numbers the primer quotes."""
    config = ProjectConfig()
    scene = normalise(decode_original(sample, config.decode, half_size=True), config)
    y = luminance(scene[::2, ::2])
    ev = linear_to_ev(y)
    levels = np.percentile(ev, [1, 5, 50, 95, 99])
    marks = {f"p{p}": float(v) for p, v in zip((1, 5, 50, 95, 99), levels, strict=True)}
    mean_ev = float(np.log2(float(np.mean(y)) / MIDDLE_GREY))
    shown = agx_display(resize_to_long_edge(scene, PANEL[0]).copy())
    del scene, y
    panels = [
        ("the photo (after normalise)", fit(shown, PANEL)),
        ("its luminance histogram in EV", histogram_panel(ev, marks, mean_ev)),
    ]
    caption = "Half-size decode. Sample: DJI FC4382, raw.pixls.us, CC0."
    return grid(panels, columns=2, caption=caption), {**marks, "mean": mean_ev}


def planckian_xy(kelvin: float) -> tuple[float, float]:
    """Chromaticity of a black body at ``kelvin`` (Kim et al. 2002 cubic fit, 1667-25000 K)."""
    t = float(kelvin)
    if t <= 4000:
        x = -0.2661239e9 / t**3 - 0.2343589e6 / t**2 + 0.8776956e3 / t + 0.179910
    else:
        x = -3.0258469e9 / t**3 + 2.1070379e6 / t**2 + 0.2226347e3 / t + 0.240390
    if t <= 2222:
        y = -1.1063814 * x**3 - 1.34811020 * x**2 + 2.18555832 * x - 0.20219683
    elif t <= 4000:
        y = -0.9549476 * x**3 - 1.37418593 * x**2 + 2.09137015 * x - 0.16748867
    else:
        y = 3.0817580 * x**3 - 5.87338670 * x**2 + 3.75112997 * x - 0.37001483
    return x, y


def light_swatch(kelvin: float, size: tuple[int, int]) -> Pixels:
    """The colour of a white card under ``kelvin`` light, to eyes adapted to daylight (D65)."""
    rgb = XYZ_TO_REC709 @ xy_to_xyz(planckian_xy(kelvin))
    rgb = np.clip(rgb / rgb.max() * 0.85, 0.0, 1.0).astype(np.float32)
    swatch = np.broadcast_to(srgb_encode(rgb), (size[1], size[0], 3))
    return quantise(np.ascontiguousarray(swatch))


def kelvin_scale() -> Image.Image:
    """Two rows of light colours: equal kelvin steps, then equal mired steps."""
    swatch, gap, label_width = (110, 44), 8, 150
    rows = [
        ("equal kelvin steps", [float(k) for k in SCALE_KELVIN]),
        ("equal mired steps", [1e6 / m for m in SCALE_MIRED]),
    ]
    row_height = swatch[1] + 30
    width = label_width + len(SCALE_KELVIN) * (swatch[0] + gap) + MARGIN
    sheet = Image.new("RGB", (width, len(rows) * row_height + 8), BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    for row, (label, kelvins) in enumerate(rows):
        y = 4 + row * row_height
        draw.text((MARGIN, y + swatch[1] // 2 - 8), label, fill=TEXT, font=font(14))
        for index, kelvin in enumerate(kelvins):
            x = label_width + index * (swatch[0] + gap)
            sheet.paste(Image.fromarray(light_swatch(kelvin, swatch)), (x, y))
            text = f"{kelvin:.0f} K, {1e6 / kelvin:.0f} mired"
            draw.text((x, y + swatch[1] + 4), text, fill=MUTED, font=font(11))
    return sheet


def grey_world_xy(scene: FloatImage) -> tuple[float, float]:
    """Plain grey-world: the photo's average colour, taken to be the colour of the light."""
    mean = scene.reshape(-1, 3).mean(axis=0).astype(np.float64)
    return xyz_to_xy(REC2020_TO_XYZ @ mean)


def white_balance_figure(sample: Path) -> tuple[Image.Image, dict[str, float]]:
    """As-shot vs grey-world white balance on a tungsten-lit photo, and a kelvin/mired scale."""
    config = ProjectConfig()
    image = decode_original(sample, config.decode, half_size=True)
    scene = normalise(resize_to_long_edge(image, PANEL[0]).copy(), config)
    del image
    colour = read_dng_colour(sample)
    if colour is None:
        raise SystemExit(f"error: {sample.name} has no DNG colour tags")
    _matrix, as_shot = dng_camera_to_working(colour)
    # Decode already maps the as-shot white to D65, so grey-world here finds the leftover
    # cast; mapping it back through the as-shot adaptation gives the light it implies.
    leftover = grey_world_xy(scene)
    estimated = xy_to_cct(xyz_to_xy(bradford_matrix(D65, as_shot.xy) @ xy_to_xyz(leftover)))
    rebalance = XYZ_TO_REC2020 @ bradford_matrix(leftover, D65) @ REC2020_TO_XYZ
    balanced = apply_matrix(scene, rebalance.astype(np.float32))
    panels = [
        (f"as shot: {as_shot.kelvin:.0f} K (the camera's record)", fit(agx_display(scene), PANEL)),
        (f"grey-world estimate: {estimated:.0f} K", fit(agx_display(balanced), PANEL)),
    ]
    jpeg = camera_jpeg(sample)
    if jpeg is not None:
        panels.append(("camera JPEG", fit(jpeg, PANEL)))
    caption = "Half-size decode. Sample: Pentax K-5 II s, raw.pixls.us, CC0."
    numbers = {
        "as_shot_kelvin": as_shot.kelvin,
        "grey_world_kelvin": estimated,
        "difference_mired": 1e6 / estimated - 1e6 / as_shot.kelvin,
    }
    return vstack([grid(panels, columns=3, caption=caption), kelvin_scale()]), numbers


def noise_figure(sample: Path) -> Image.Image:
    """A dark, high-ISO crop: luma vs chroma noise, chroma NR, luma NR, and the output size."""
    config = ProjectConfig()
    scene = decode_original(sample, config.decode, half_size=True)
    apply_exposure(scene, exposure_ev(scene, config.normalise.exposure), out=scene)
    top, left, height, width = NOISE_CROP
    rows, columns = slice(top, top + height), slice(left, left + width)
    noisy = scene[rows, columns].copy()
    whole = resize_to_long_edge(scene, NOISE_PANEL[0]).copy()
    chroma_noise_reduction(scene, config.normalise.chroma_nr)
    reduced = scene[rows, columns].copy()
    del scene

    y = luminance(noisy)
    luma_only = np.ascontiguousarray(np.repeat(y[..., None], 3, axis=2))
    smooth_y = gaussian_blur(np.ascontiguousarray(y[..., None]), 2.0)[..., 0]
    # Each pixel's own colour at its neighbourhood's brightness (ratio capped where y ~ 0).
    ratio = np.clip(smooth_y / np.maximum(y, np.float32(1e-6)), 0.0, 4.0)
    chroma_only = noisy * ratio[..., None]
    luma_reduced = gaussian_blur(reduced, LUMA_NR_SIGMA)

    def zoom(image: FloatImage) -> Image.Image:
        bright = image * np.float32(2.0**NOISE_BRIGHTEN_EV)
        pixels = agx_display(np.ascontiguousarray(bright, dtype=np.float32))
        return Image.fromarray(pixels).resize(NOISE_PANEL, Image.Resampling.NEAREST)

    panels = [
        ("1  100 % crop, no noise reduction", zoom(noisy)),
        ("2  its luma (brightness) noise", zoom(luma_only)),
        ("3  its chroma (colour) noise", zoom(chroma_only)),
        ("4  after chroma NR (picturesq)", zoom(reduced)),
        ("5  plus a luma blur", zoom(luma_reduced)),
        ("6  whole photo, output size, no NR", fit(agx_display(whole), NOISE_PANEL)),
    ]
    caption = (
        f"Crops 1-5: enlarged {NOISE_ZOOM}x and shown {NOISE_BRIGHTEN_EV:g} stops brighter. "
        "Half-size decode. Sample: Sony ILME-FX3, ISO 20000, raw.pixls.us, CC0."
    )
    return grid(panels, columns=3, caption=caption)


def intensity_figure(sample: Path) -> Image.Image:
    """The DJI sample through cold/nordic at 0, 50, 100 and 150 % (preview renders)."""
    from picturesq.config import AdjustmentsConfig, LookChoice, look_library
    from picturesq.pipeline.looks import resolve_choice
    from picturesq.preview.look_sheet import Variant, render_variant

    config = ProjectConfig()
    scene = normalise(decode_original(sample, config.decode, half_size=True), config)
    library = look_library()
    panels = []
    for intensity in (0.0, 0.5, 1.0, 1.5):
        look = resolve_choice(LookChoice(name="cold/nordic", intensity=intensity), library)
        variant = Variant("", look, AdjustmentsConfig())
        pixels = render_variant(scene, config, sample.name, None, variant)
        panels.append((f"cold/nordic {round(intensity * 100)} %", fit(pixels, (360, 270))))
    return grid(panels, 4, "Intensity scales each operation's strength: 0 % is the neutral render.")


def tone_curve_figure() -> Image.Image:
    """EV in vs EV out: identity, contrast 0.2 and a soft-highlights tone curve."""
    from picturesq.config.operations import ContrastOperation, ToneCurveOperation
    from picturesq.grade.operations import apply_operation

    evs = np.linspace(-6.0, 6.0, 241)
    curves = {
        "identity": (evs, MUTED),
        "contrast 0.2": (None, (40, 110, 200)),
        "tone_curve [[0,0],[2,1.5],[4,2.5]]": (None, ACCENT),
    }
    operations = {
        "contrast 0.2": ContrastOperation(amount=0.2),
        "tone_curve [[0,0],[2,1.5],[4,2.5]]": ToneCurveOperation(
            points=((0.0, 0.0), (2.0, 1.5), (4.0, 2.5))
        ),
    }
    for name, operation in operations.items():
        greys = np.repeat((MIDDLE_GREY * 2.0**evs)[:, None], 3, axis=1).astype(np.float32)[None]
        out = apply_operation(greys, operation)[0, :, 1]
        curves[name] = (np.log2(out / MIDDLE_GREY), curves[name][1])
    size, pad = 480, 50
    image = Image.new("RGB", (size + 2 * pad + 260, size + 2 * pad), BACKGROUND)
    draw = ImageDraw.Draw(image)

    def at(x: float, y: float) -> tuple[float, float]:
        return pad + (x + 6) / 12 * size, pad + (6 - y) / 12 * size

    for tick in range(-6, 7, 2):
        draw.line([at(tick, -6), at(tick, 6)], fill=(225, 225, 225))
        draw.line([at(-6, tick), at(6, tick)], fill=(225, 225, 225))
        draw.text((at(tick, -6)[0] - 6, size + pad + 6), f"{tick:+d}", fill=MUTED, font=font(12))
        draw.text((pad - 30, at(-6, tick)[1] - 7), f"{tick:+d}", fill=MUTED, font=font(12))
    for index, (name, (values, colour)) in enumerate(curves.items()):
        draw.line([at(x, y) for x, y in zip(evs, values, strict=True)], fill=colour, width=3)
        draw.text((size + 2 * pad, pad + 24 * index), name, fill=colour, font=font(14))
    draw.text((pad, 12), "scene EV in (x) vs EV out (y), mid grey = 0", fill=TEXT, font=font(14))
    return image


def hue_band_figure() -> Image.Image:
    """The eight hsl hue bands: an Oklab hue strip with each band's centre marked."""
    from picturesq.colour.oklab import oklab_to_rec709
    from picturesq.config.operations import HUE_BANDS

    width, height = 720, 60
    hues = np.radians(np.linspace(0.0, 360.0, width, endpoint=False))
    lab = np.stack([np.full(width, 0.72), 0.12 * np.cos(hues), 0.12 * np.sin(hues)], -1)
    rgb = np.clip(oklab_to_rec709(lab.astype(np.float32)), 0.0, 1.0)
    strip = quantise(srgb_encode(rgb))[None].repeat(height, axis=0)
    image = Image.new("RGB", (width + 2 * MARGIN, height + 70), BACKGROUND)
    image.paste(Image.fromarray(strip), (MARGIN, 30))
    draw = ImageDraw.Draw(image)
    draw.text(
        (MARGIN, 6), "Oklab hue 0-360 at lightness 0.72, chroma 0.12", fill=TEXT, font=font(14)
    )
    for name, centre in HUE_BANDS.items():
        x = MARGIN + centre / 360.0 * width
        draw.line([(x, 30), (x, 30 + height)], fill=TEXT, width=1)
        draw.text((x - 18, 36 + height), name, fill=TEXT, font=font(12))
    return image


def check_sample(path: Path) -> None:
    manifest = json.loads((ROOT / "reference" / "samples.json").read_text())
    entry = next(s for s in manifest["samples"] if s["name"] == path.name)
    if not path.is_file():
        raise SystemExit(f"error: {path} not found; run scripts/fetch_samples.py")
    if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
        raise SystemExit(f"error: {path} does not match the checksum in samples.json")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out-dir", type=Path, default=ROOT / "docs" / "primers" / "images")
    parser.add_argument("--only", choices=("m1", "m2", "m3"), help="render one primer's figures")
    args = parser.parse_args()
    samples_dir = Path(os.environ.get("PICTURESQ_SAMPLES", ROOT / "reference" / "samples"))
    sample, wb_sample, noise_sample = (
        samples_dir / name for name in (SAMPLE, WB_SAMPLE, NOISE_SAMPLE)
    )
    for path in (sample, wb_sample, noise_sample):
        check_sample(path)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    figures: dict[str, Image.Image] = {}
    if args.only in (None, "m1"):
        figures["m1-bayer-mosaic.jpg"] = mosaic_figure(sample)
        figures["m1-display-transforms.jpg"] = display_figure(sample)
        figures["m1-ramps.jpg"] = ramp_figure()
    if args.only in (None, "m2"):
        # One figure at a time, so only one decode is in memory.
        figures["m2-histogram.jpg"], levels = histogram_figure(sample)
        print("histogram, EV:", {k: round(v, 2) for k, v in levels.items()})
        figures["m2-white-balance.jpg"], white = white_balance_figure(wb_sample)
        print("white balance:", {k: round(v) for k, v in white.items()})
        figures["m2-noise.jpg"] = noise_figure(noise_sample)
    if args.only in (None, "m3"):
        figures["m3-intensity.jpg"] = intensity_figure(sample)
        figures["m3-tone-curves.jpg"] = tone_curve_figure()
        figures["m3-hue-bands.jpg"] = hue_band_figure()
    for name, figure in figures.items():
        path = args.out_dir / name
        # Fixed settings and no EXIF, so re-running gives the same bytes.
        figure.save(path, quality=QUALITY, optimize=True, progressive=False)
        print(f"wrote {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}", end="")
        print(f" ({figure.width}x{figure.height}, {path.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
