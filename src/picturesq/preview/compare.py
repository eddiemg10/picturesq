"""Measure an export against the camera's own JPEG (pure helpers behind scripts/compare.py).

The gate (ADR-0010) compares the *real* export, not an exposure-matched one:

- **brightness:** median luminance difference in EV; across a set, the median of
  ``|difference|`` must be at most ``MAX_MEDIAN_EV``.
- **colour:** mean Oklab chroma per lightness band. Across a set, each band's chroma is
  summed over the photos for us and for the camera, and the ratio must lie in
  ``CHROMA_RATIO_RANGE``. Pooling keeps near-white bands (chroma ≈ 0 in both) from
  producing meaningless ratios of tiny numbers.
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
    """Our mean chroma per lightness band (NaN where a band is nearly empty)."""
    camera_chroma: tuple[float, ...]
    content_correlation: float
    """Correlation of the two images' coarse luminance; low means a different frame."""

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
    """Compare two renders of one photo. They may differ in size, not in content."""
    floor = 1e-6
    ev = np.log2(
        max(median_luminance_linear(ours), floor) / max(median_luminance_linear(camera), floor)
    )
    return PhotoComparison(
        name=name,
        ev_difference=float(ev),
        clipped=float(clipped_mask(ours).mean()),
        camera_clipped=float(clipped_mask(camera).mean()),
        chroma=tuple(float(c) for c in chroma_by_band(ours)),
        camera_chroma=tuple(float(c) for c in chroma_by_band(camera)),
        content_correlation=content_correlation(ours, camera),
    )


def gate(photos: Sequence[PhotoComparison]) -> GateResult:
    """Apply the ADR-0010 gate to the photos whose camera JPEG is the same frame."""
    photos = [p for p in photos if p.same_frame]
    ours = np.array([p.chroma for p in photos], dtype=np.float64).reshape(len(photos), -1)
    camera = np.array([p.camera_chroma for p in photos], dtype=np.float64).reshape(ours.shape)
    both = ~(np.isnan(ours) | np.isnan(camera))
    with np.errstate(invalid="ignore", divide="ignore"):
        band = np.where(both, ours, 0.0).sum(axis=0) / np.where(both, camera, 0.0).sum(axis=0)
    over = tuple(p.name for p in photos if p.clipped > p.camera_clipped + MAX_EXTRA_CLIPPED)
    return GateResult(
        median_abs_ev=float(np.median([abs(p.ev_difference) for p in photos])) if photos else 0.0,
        band_chroma_ratio=tuple(float(b) for b in band),
        over_clipped=over,
    )
