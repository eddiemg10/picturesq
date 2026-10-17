"""Measure an export against the camera's own JPEG (pure helpers behind scripts/compare.py).

The gate (ADR-0010) compares the *real* export, not an exposure-matched one:

- **brightness:** median luminance difference in EV; across a set, the median of
  ``|difference|`` must be at most ``MAX_MEDIAN_EV``.
- **colour:** mean Oklab chroma per lightness band, measured at the same pixels in both
  images (``aligned_chroma_by_band``): ours is aligned to the camera JPEG and each pixel
  goes in the band of the *camera's* lightness there. Banding each image by its own
  lightness would compare different parts of the picture whenever the brightness
  differs, so a brightness error would show up as a colour error (#58). Across a set,
  each band's chroma is summed over the photos for us and for the camera, and the ratio
  must lie in ``CHROMA_RATIO_RANGE``. Pooling keeps near-white bands (chroma ≈ 0 in
  both) from producing meaningless ratios of tiny numbers.
- **highlights:** per photo, our clipped fraction may exceed the camera's by at most
  ``MAX_EXTRA_CLIPPED``.

Photos whose embedded JPEG is not the same frame as the RAW are left out: some cameras
(the DJI Pocket 4 in burst mode) embed a neighbouring frame. ``content_correlation`` below
``MIN_CONTENT_CORRELATION`` marks them.
"""

import itertools
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from picturesq.colour.oklab import rec2020_to_oklab
from picturesq.colour.spaces import REC709_TO_REC2020, REC709_TO_XYZ, apply_matrix
from picturesq.colour.transfer import srgb_decode
from picturesq.preview.stage_sheet import clipped_mask

Uint8Array = NDArray[np.uint8]

MAX_MEDIAN_EV = 0.5
CHROMA_RATIO_RANGE = (0.8, 1.25)
MAX_EXTRA_CLIPPED = 0.005
LIGHTNESS_BANDS = (0.0, 0.25, 0.4, 0.55, 0.7, 0.85, 1.01)
"""Oklab lightness band edges (0.18 grey is L ≈ 0.565)."""
MIN_BAND_PIXELS = 200
MIN_CONTENT_CORRELATION = 0.85
ALIGN_LONG_EDGE = 1024
"""Long edge both images are compared at for the aligned measure."""
MAX_SHIFT = 0.05
"""Largest shift between the two framings the alignment looks for, as a fraction of a side."""
ALIGN_ZOOMS = tuple(float(z) for z in np.linspace(1.0, 0.93, 15))
"""Centred crops of ours (fraction of the frame) tried against the camera JPEG's framing."""
_THUMB_SIZE = (48, 32)


@dataclass(frozen=True)
class PhotoComparison:
    """One photo: ours against the camera's JPEG."""

    name: str
    ev_difference: float
    """``log2(our median luminance / camera's)``: positive = ours is brighter."""
    clipped: float
    camera_clipped: float
    chroma: tuple[float, ...]
    """Our mean chroma at the pixels in each band of the camera's lightness (NaN where a
    band is nearly empty)."""
    camera_chroma: tuple[float, ...]
    content_correlation: float
    """Correlation of the two images' coarse luminance; low means a different frame."""
    own_band_chroma: tuple[float, ...] = ()
    """Our mean chroma per band of *our* lightness (the measure before #58; for display)."""
    camera_own_band_chroma: tuple[float, ...] = ()

    @property
    def same_frame(self) -> bool:
        return self.content_correlation >= MIN_CONTENT_CORRELATION

    @property
    def chroma_ratio(self) -> tuple[float, ...]:
        """Our mean chroma / the camera's, per band (for display; the gate pools)."""
        with np.errstate(invalid="ignore", divide="ignore"):
            return tuple(float(a / b) for a, b in zip(self.chroma, self.camera_chroma, strict=True))


@dataclass(frozen=True)
class GateResult:
    median_abs_ev: float
    band_chroma_ratio: tuple[float, ...]
    over_clipped: tuple[str, ...]

    @property
    def brightness_ok(self) -> bool:
        return self.median_abs_ev <= MAX_MEDIAN_EV

    @property
    def colour_ok(self) -> bool:
        low, high = CHROMA_RATIO_RANGE
        ratios = [r for r in self.band_chroma_ratio if not np.isnan(r)]
        return all(low <= r <= high for r in ratios)

    @property
    def highlights_ok(self) -> bool:
        return not self.over_clipped

    @property
    def passed(self) -> bool:
        return self.brightness_ok and self.colour_ok and self.highlights_ok


def _linear(pixels: Uint8Array) -> NDArray[np.float32]:
    return srgb_decode(pixels.astype(np.float32) / np.float32(255.0))


def median_luminance_linear(pixels: Uint8Array) -> float:
    """Median display-linear luminance (Rec.709 Y) of an sRGB 8-bit image."""
    return float(np.median(_linear(pixels) @ REC709_TO_XYZ[1].astype(np.float32)))


def chroma_by_band(pixels: Uint8Array) -> NDArray[np.float64]:
    """Mean Oklab chroma of an sRGB 8-bit image in each ``LIGHTNESS_BANDS`` band."""
    lab = rec2020_to_oklab(apply_matrix(_linear(pixels), REC709_TO_REC2020)).reshape(-1, 3)
    lightness, chroma = lab[:, 0], np.hypot(lab[:, 1], lab[:, 2])
    means = []
    for low, high in itertools.pairwise(LIGHTNESS_BANDS):
        inside = (lightness >= low) & (lightness < high)
        means.append(float(chroma[inside].mean()) if inside.sum() >= MIN_BAND_PIXELS else np.nan)
    return np.array(means)


def _resized(
    pixels: Uint8Array, size: tuple[int, int], box: tuple[int, int, int, int]
) -> Uint8Array:
    image = Image.fromarray(pixels).resize(size, Image.Resampling.BOX, box=box)
    return np.asarray(image, dtype=np.uint8)


def _shift(a: NDArray[np.float64], b: NDArray[np.float64]) -> tuple[int, int]:
    """``(dy, dx)`` such that ``a[y + dy, x + dx]`` best matches ``b[y, x]`` (phase correlation)."""
    spectrum = np.fft.fft2(a - a.mean()) * np.fft.fft2(b - b.mean()).conj()
    spectrum /= np.maximum(np.abs(spectrum), 1e-12)
    correlation = np.fft.ifft2(spectrum).real
    height, width = a.shape
    limit_y, limit_x = int(MAX_SHIFT * height) + 1, int(MAX_SHIFT * width) + 1
    # Only small shifts are plausible; wrap the others out of the search.
    ys = np.r_[0:limit_y, height - limit_y + 1 : height]
    xs = np.r_[0:limit_x, width - limit_x + 1 : width]
    window = correlation[np.ix_(ys, xs)]
    y, x = np.unravel_index(int(np.argmax(window)), window.shape)
    dy, dx = int(ys[y]), int(xs[x])
    return (dy - height if dy > height // 2 else dy), (dx - width if dx > width // 2 else dx)


def align(ours: Uint8Array, camera: Uint8Array) -> tuple[Uint8Array, Uint8Array]:
    """Both images at the same size, showing the same content pixel for pixel.

    Ours is cropped (centred) to the camera JPEG's aspect and both are reduced to
    ``ALIGN_LONG_EDGE``. Cameras often frame a little tighter than the RAW (sensor
    margins, in-camera distortion correction), so a centred zoom of ours in
    ``ALIGN_ZOOMS`` is tried, each with the remaining shift found by phase correlation,
    and the one whose pixels correlate best is kept. The shift is cropped from both.
    """
    camera_height, camera_width = camera.shape[:2]
    height, width = ours.shape[:2]
    aspect = camera_width / camera_height
    if width / height > aspect:
        full_width, full_height = height * aspect, float(height)
    else:
        full_width, full_height = float(width), width / aspect
    scale = min(1.0, ALIGN_LONG_EDGE / max(camera_width, camera_height))
    size = (max(1, round(camera_width * scale)), max(1, round(camera_height * scale)))
    camera_small = _resized(camera, size, (0, 0, camera_width, camera_height))
    camera_luminance = _luminance(camera_small)
    best: tuple[float, Uint8Array, Uint8Array] | None = None
    for zoom in ALIGN_ZOOMS:
        crop_width, crop_height = full_width * zoom, full_height * zoom
        left, top = (width - crop_width) / 2, (height - crop_height) / 2
        box = (round(left), round(top), round(left + crop_width), round(top + crop_height))
        ours_small = _resized(ours, size, box)
        ours_luminance = _luminance(ours_small)
        dy, dx = _shift(ours_luminance, camera_luminance)
        h, w = size[1], size[0]
        rows_ours, columns_ours = (
            slice(max(dy, 0), h + min(dy, 0)),
            slice(max(dx, 0), w + min(dx, 0)),
        )
        rows_camera = slice(max(-dy, 0), h + min(-dy, 0))
        columns_camera = slice(max(-dx, 0), w + min(-dx, 0))
        a = ours_luminance[rows_ours, columns_ours].ravel()
        b = camera_luminance[rows_camera, columns_camera].ravel()
        score = float(np.corrcoef(a, b)[0, 1]) if a.std() > 0 and b.std() > 0 else -1.0
        if best is None or score > best[0]:
            best = (
                score,
                ours_small[rows_ours, columns_ours],
                camera_small[rows_camera, columns_camera],
            )
    assert best is not None
    return best[1], best[2]


def _luminance(pixels: Uint8Array) -> NDArray[np.float64]:
    return (_linear(pixels) @ REC709_TO_XYZ[1].astype(np.float32)).astype(np.float64)


def _oklab(pixels: Uint8Array) -> NDArray[np.float32]:
    return rec2020_to_oklab(apply_matrix(_linear(pixels), REC709_TO_REC2020)).reshape(-1, 3)


def aligned_chroma_by_band(
    ours: Uint8Array, camera: Uint8Array
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Mean Oklab chroma of ours and the camera's at the same pixels, per band of the
    camera's lightness. ``ours`` and ``camera`` must already be aligned (``align``)."""
    lab_ours, lab_camera = _oklab(ours), _oklab(camera)
    lightness = lab_camera[:, 0]
    chroma_ours = np.hypot(lab_ours[:, 1], lab_ours[:, 2])
    chroma_camera = np.hypot(lab_camera[:, 1], lab_camera[:, 2])
    means_ours, means_camera = [], []
    for low, high in itertools.pairwise(LIGHTNESS_BANDS):
        inside = (lightness >= low) & (lightness < high)
        enough = inside.sum() >= MIN_BAND_PIXELS
        means_ours.append(float(chroma_ours[inside].mean()) if enough else np.nan)
        means_camera.append(float(chroma_camera[inside].mean()) if enough else np.nan)
    return np.array(means_ours), np.array(means_camera)


def content_correlation(ours: Uint8Array, camera: Uint8Array) -> float:
    """Pearson correlation of both images' luminance on a coarse grid (sizes may differ)."""
    thumbs = []
    for pixels in (ours, camera):
        luminance = _linear(pixels) @ REC709_TO_XYZ[1].astype(np.float32)
        thumb = Image.fromarray(luminance, "F").resize(_THUMB_SIZE, Image.Resampling.BOX)
        thumbs.append(np.asarray(thumb, dtype=np.float64).ravel())
    if thumbs[0].std() == 0.0 or thumbs[1].std() == 0.0:
        return 0.0
    return float(np.corrcoef(thumbs[0], thumbs[1])[0, 1])


def compare_photo(name: str, ours: Uint8Array, camera: Uint8Array) -> PhotoComparison:
    """Compare two renders of one photo. They may differ in size and framing a little
    (sensor margins, a crop), not in content."""
    floor = 1e-6
    aligned_ours, aligned_camera = align(ours, camera)
    chroma, camera_chroma = aligned_chroma_by_band(aligned_ours, aligned_camera)
    ev = np.log2(
        max(median_luminance_linear(ours), floor) / max(median_luminance_linear(camera), floor)
    )
    return PhotoComparison(
        name=name,
        ev_difference=float(ev),
        clipped=float(clipped_mask(ours).mean()),
        camera_clipped=float(clipped_mask(camera).mean()),
        chroma=tuple(float(c) for c in chroma),
        camera_chroma=tuple(float(c) for c in camera_chroma),
        content_correlation=content_correlation(aligned_ours, aligned_camera),
        own_band_chroma=tuple(float(c) for c in chroma_by_band(ours)),
        camera_own_band_chroma=tuple(float(c) for c in chroma_by_band(camera)),
    )


def pooled_ratio(
    ours: Sequence[Sequence[float]], camera: Sequence[Sequence[float]]
) -> tuple[float, ...]:
    """Per band: our chroma summed over photos / the camera's (bands missing in either
    image of a photo are left out of both sums)."""
    if not ours:
        return ()
    a = np.array(ours, dtype=np.float64).reshape(len(ours), -1)
    b = np.array(camera, dtype=np.float64).reshape(a.shape)
    both = ~(np.isnan(a) | np.isnan(b))
    with np.errstate(invalid="ignore", divide="ignore"):
        band = np.where(both, a, 0.0).sum(axis=0) / np.where(both, b, 0.0).sum(axis=0)
    return tuple(float(r) for r in band)


def gate(photos: Sequence[PhotoComparison]) -> GateResult:
    """Apply the ADR-0010 gate to the photos whose camera JPEG is the same frame."""
    photos = [p for p in photos if p.same_frame]
    band = pooled_ratio([p.chroma for p in photos], [p.camera_chroma for p in photos])
    over = tuple(p.name for p in photos if p.clipped > p.camera_clipped + MAX_EXTRA_CLIPPED)
    return GateResult(
        median_abs_ev=float(np.median([abs(p.ev_difference) for p in photos])) if photos else 0.0,
        band_chroma_ratio=band,
        over_clipped=over,
    )
