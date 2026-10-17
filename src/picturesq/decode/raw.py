"""Decode an original (RAW file) into a scene-linear image in the working space.

Output: float32 ``HxWx3``, linear light, Rec.2020 primaries, D65 white, C-contiguous. Out-of-gamut
colours keep a negative channel. The image is
oriented upright (LibRaw applies the file's orientation tag; we leave ``user_flip`` at its default).
The DNG ``BaselineExposure`` is applied, so middle grey sits near 0.18 for a well-exposed DNG;
values above 1.0 are kept (scene-linear headroom). Exposure normalisation across photos is M2.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import numpy as np
import rawpy
from numpy.typing import NDArray

# rawpy re-exports these at runtime, but its type stubs only declare them in rawpy._rawpy.
from rawpy._rawpy import ColorSpace, DemosaicAlgorithm, HighlightMode, LibRawError, RawPy

from picturesq.colour.spaces import REC709_TO_REC2020, REC709_TO_XYZ, Matrix, apply_matrix
from picturesq.config.project import DecodeConfig
from picturesq.decode.dng_colour import dng_camera_to_working, read_dng_colour
from picturesq.decode.exposure import read_baseline_exposure
from picturesq.decode.opcodes import NO_CORRECTIONS, apply_lens_corrections, read_lens_corrections

# Keyed by the Literal values of ``DecodeConfig.demosaic``. LibRaw ignores this choice for X-Trans
# (Fuji) sensors and always uses its own X-Trans demosaic.
DEMOSAIC_ALGORITHMS: Final[dict[str, DemosaicAlgorithm]] = {
    "linear": DemosaicAlgorithm.LINEAR,
    "vng": DemosaicAlgorithm.VNG,
    "ppg": DemosaicAlgorithm.PPG,
    "ahd": DemosaicAlgorithm.AHD,
    "dcb": DemosaicAlgorithm.DCB,
    "dht": DemosaicAlgorithm.DHT,
    "aahd": DemosaicAlgorithm.AAHD,
}

# Keyed by the Literal values of ``DecodeConfig.highlight_mode``.
HIGHLIGHT_MODES: Final[dict[str, HighlightMode]] = {
    "clip": HighlightMode.Clip,
    "ignore": HighlightMode.Ignore,
    "blend": HighlightMode.Blend,
    "reconstruct": HighlightMode.ReconstructDefault,
}

_UINT16_MAX: Final = 65535.0

Box = tuple[int, int, int, int]
"""``(top, left, height, width)`` in pixels."""


class DecodeError(Exception):
    """An original could not be read or decoded (unreadable, corrupt or unsupported)."""


def camera_to_working_matrix(
    rgb_cam: NDArray[np.floating], cam_xyz: NDArray[np.floating]
) -> Matrix:
    """The matrix taking white-balanced camera RGB to linear Rec.2020.

    ``rgb_cam`` is LibRaw's camera → linear sRGB matrix (rawpy ``color_matrix``, filled for
    DNGs); ``cam_xyz`` is the XYZ → camera matrix (rawpy ``rgb_xyz_matrix``, filled for most
    other RAWs). Either may be all zeros. Without ``rgb_cam`` we derive it from ``cam_xyz``
    the way dcraw does: camera ← sRGB is ``cam_xyz @ srgb_to_xyz``, each row scaled to sum to
    1 (so white-balanced white stays white), then inverted. sRGB and Rec.709 share primaries.
    """
    rgb_cam = np.asarray(rgb_cam, dtype=np.float64)[:3, :3]
    if not np.any(rgb_cam):
        cam_xyz = np.asarray(cam_xyz, dtype=np.float64)[:3, :3]
        if not np.any(cam_xyz):
            raise ValueError("the RAW file has no colour matrix")
        cam_rgb = cam_xyz @ REC709_TO_XYZ
        cam_rgb /= cam_rgb.sum(axis=1, keepdims=True)
        rgb_cam = np.linalg.inv(cam_rgb)
    return REC709_TO_REC2020 @ rgb_cam


def decode_original(
    path: Path, config: DecodeConfig, *, half_size: bool = False
) -> NDArray[np.float32]:
    """Decode the original at ``path`` to a scene-linear float32 ``HxWx3`` image.

    ``half_size`` skips demosaicing (each 2x2 block becomes one pixel): much faster, for proxies
    and tests.

    Colour: LibRaw demosaics and white-balances in camera RGB (``output_color=raw``), and we
    convert camera RGB to linear Rec.2020 ourselves in float32. For DNGs (with
    ``config.colour_matrix == "dng"``) the matrix follows the DNG specification, blending the
    file's two colour matrices by the as-shot white (``decode/dng_colour.py``, ADR-0012);
    otherwise it is LibRaw's (:func:`camera_to_working_matrix`).
    LibRaw's own conversion stores 16-bit unsigned integers, which clips every out-of-gamut
    colour (a negative channel) to 0 before we see it (#47). Ours keeps negatives.

    Lens corrections: if ``config.lens_corrections`` is set, the DNG's ``OpcodeList3`` gain
    maps (vignetting) and rectilinear warps (distortion, lateral chromatic aberration) are
    applied in camera RGB, before the colour matrix (``decode/opcodes.py``).

    If ``config.default_crop`` is set, the image is cropped to the frame the original specifies
    (:func:`default_crop_box`).

    If ``config.baseline_exposure`` is set, the DNG ``BaselineExposure`` (stops) is applied as a
    linear gain ``2**ev``: some cameras record the raw 2 to 4 stops dark on purpose, and without
    this every render comes out dark. The result is not clipped, so values can exceed 1.0. No
    other brightness scaling happens here (no auto-brightness): matching exposure across photos
    is the job of the normalise stage.
    """
    try:
        gain = 2.0 ** read_baseline_exposure(path) if config.baseline_exposure else 1.0
        corrections = read_lens_corrections(path) if config.lens_corrections else NO_CORRECTIONS
        dng_colour = read_dng_colour(path) if config.colour_matrix == "dng" else None
        with rawpy.imread(str(path)) as raw:
            if dng_colour is not None:
                matrix, _white = dng_camera_to_working(dng_colour)
            else:
                matrix = camera_to_working_matrix(raw.color_matrix, raw.rgb_xyz_matrix)
            if raw.sizes.flip != 0:
                # The opcodes are in sensor orientation; we have no sample to verify LibRaw's
                # rotation codes against, so we don't guess.
                corrections = NO_CORRECTIONS
            sizes = raw.sizes
            rgb16 = raw.postprocess(
                demosaic_algorithm=DEMOSAIC_ALGORITHMS[config.demosaic],
                highlight_mode=HIGHLIGHT_MODES[config.highlight_mode],
                half_size=half_size,
                use_camera_wb=True,
                no_auto_bright=True,
                gamma=(1, 1),
                output_bps=16,
                output_color=ColorSpace.raw,
            )
    except (LibRawError, OSError, ValueError) as err:
        raise DecodeError(f"cannot decode {path.name}: {err}") from err

    box = default_crop_box(sizes, rgb16.shape[:2]) if config.default_crop else None
    if corrections:
        # The warps are defined on the whole image, so they run before the crop.
        image = apply_lens_corrections(rgb16, corrections, gain / _UINT16_MAX)
        if box is not None:
            image = np.ascontiguousarray(_crop(image, box))
    else:
        if box is not None:
            rgb16 = _crop(rgb16, box)  # a view: the conversion below writes only the crop
        image = np.empty(rgb16.shape, dtype=np.float32)
        np.multiply(rgb16, np.float32(gain / _UINT16_MAX), out=image, dtype=np.float32)
    del rgb16
    return apply_matrix_in_blocks(image, matrix)


def read_pixel_count(path: Path) -> int:
    """Pixels the decoded image of ``path`` has at most (before the default crop).

    Reads only the file's header (milliseconds): nothing is unpacked or demosaiced. Used to
    size the worker pool before any photo is decoded. Raises DecodeError like decoding.
    """
    raw = RawPy()
    try:
        raw.open_file(str(path))
        return int(raw.sizes.width) * int(raw.sizes.height)
    except (LibRawError, OSError, ValueError) as err:
        raise DecodeError(f"cannot read {path.name}: {err}") from err
    finally:
        raw.close()


def default_crop_box(sizes: Any, shape: tuple[int, int]) -> Box | None:
    """The frame the original specifies, in LibRaw's output (``shape``, upright), or None.

    LibRaw reads it (the DNG ``DefaultCropOrigin``/``DefaultCropSize``, or a maker's
    equivalent) into ``sizes.crop_*`` in raw coordinates, which include the masked
    ``left_margin``/``top_margin`` its output leaves out. Its output is upright: ``flip`` 3
    is 180°, 5 is 90° counter-clockwise, 6 is 90° clockwise (checked with ``user_flip``).
    A half-size output is scaled down by the same factor. Returns None when there is no
    crop or it doesn't fit.
    """
    top = sizes.crop_top_margin - sizes.top_margin
    left = sizes.crop_left_margin - sizes.left_margin
    height, width = sizes.crop_height, sizes.crop_width
    if height <= 0 or width <= 0:
        return None
    full_height, full_width = sizes.height, sizes.width
    rotated = sizes.flip in (5, 6)
    out_height, out_width = (shape[1], shape[0]) if rotated else shape  # sensor orientation
    scale = out_width / full_width
    if abs(out_height / full_height - scale) > 1e-3:
        return None
    top, left = int(top * scale), int(left * scale)
    height, width = int(height * scale), int(width * scale)
    if top < 0 or left < 0 or top + height > out_height or left + width > out_width:
        return None
    if (top, left, height, width) == (0, 0, out_height, out_width):
        return None
    if sizes.flip == 3:
        return out_height - top - height, out_width - left - width, height, width
    if sizes.flip == 5:
        return out_width - left - width, top, width, height
    if sizes.flip == 6:
        return left, out_height - top - height, width, height
    return top, left, height, width


def _crop(image: NDArray[Any], box: Box) -> NDArray[Any]:
    top, left, height, width = box
    return image[top : top + height, left : left + width]


def apply_matrix_in_blocks(image: NDArray[np.float32], matrix: Matrix) -> NDArray[np.float32]:
    """``apply_matrix`` in place, a block of rows at a time so the temporary copy stays small."""
    rows = max(1, (1 << 18) // max(1, image.shape[1]))
    for top in range(0, image.shape[0], rows):
        block = image[top : top + rows]
        apply_matrix(block, matrix, out=block)
    return image
