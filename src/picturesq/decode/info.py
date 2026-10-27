"""Photo info: what the original's header says about white balance and highlights.

**As-shot white.** The camera records the white balance it chose as per-channel multipliers
(LibRaw's ``cam_mul``; a DNG stores their inverse, ``AsShotNeutral``: the camera RGB of a
neutral surface). Through the camera's colour matrix that neutral becomes a chromaticity
(xy), and from there a colour temperature in kelvin and a tint. DNGs use the same
DNG-specification white the decode's matrix is computed for
(:mod:`picturesq.decode.dng_colour`); other RAWs use LibRaw's multipliers and its
XYZ → camera matrix (``rgb_xyz_matrix``, the maker's daylight matrix).

**Clip level.** The scene-linear value at which the decoded image is clipped because the sensor
saturated. It isn't simply 1.0: see :func:`clip_level`.

**Cost.** DNGs are read from their TIFF tags only (a few milliseconds). For other RAWs the
values are in LibRaw's header too, but rawpy only exposes them after unpacking the raw data
(about a second and 2 bytes per pixel; still no demosaic).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray

# rawpy re-exports these at runtime, but its type stubs only declare them in rawpy._rawpy.
from rawpy._rawpy import LibRawError, RawPy

from picturesq.colour.temperature import xy_to_kelvin_tint, xyz_to_xy
from picturesq.config.project import DecodeConfig
from picturesq.decode.dng_colour import DngColour, dng_camera_to_working, read_dng_colour
from picturesq.decode.exposure import read_baseline_exposure
from picturesq.decode.raw import DecodeError

_DIGITS: Final = 6
"""Rounding of floats in :meth:`PhotoInfo.to_dict` (stable, readable JSON)."""


@dataclass(frozen=True)
class PhotoInfo:
    """What the original's header says about one photo's white balance and highlights."""

    as_shot_xy: tuple[float, float] | None
    """CIE 1931 xy of the as-shot white (the light the camera balanced for); None if unknown."""
    as_shot_kelvin: float | None
    """Correlated colour temperature of the as-shot white, in kelvin."""
    as_shot_tint: float | None
    """Distance of the as-shot white from the black-body line: ``-1000 * Duv``, so positive is
    magenta (below the line) and negative is green (above it)."""
    baseline_exposure_ev: float
    """The DNG ``BaselineExposure`` tag in stops (0.0 when absent), whether or not
    ``decode.baseline_exposure`` applies it."""
    clip_level: float
    """Scene-linear value a white the sensor clipped reaches in the decoded image (all three
    working-space channels; see :func:`clip_level`)."""

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready: plain floats (rounded), lists and None."""

        def number(value: float | None) -> float | None:
            return None if value is None else round(float(value), _DIGITS)

        return {
            "as_shot_xy": None
            if self.as_shot_xy is None
            else [number(self.as_shot_xy[0]), number(self.as_shot_xy[1])],
            "as_shot_kelvin": number(self.as_shot_kelvin),
            "as_shot_tint": number(self.as_shot_tint),
            "baseline_exposure_ev": number(self.baseline_exposure_ev),
            "clip_level": number(self.clip_level),
        }


def read_photo_info(path: Path, config: DecodeConfig) -> PhotoInfo:
    """Read the photo info of the original at ``path`` from its header.

    ``config`` decides what the decode would do: the colour matrix (which as-shot white),
    the highlight mode and whether the baseline exposure is applied (both change the clip
    level). Raises DecodeError like decoding.
    """
    try:
        ev = read_baseline_exposure(path)
        dng_colour = read_dng_colour(path)
        neutral = None if dng_colour is None else dng_colour.as_shot_neutral
        if dng_colour is not None and neutral is not None and np.all(neutral > 0):
            multipliers = 1.0 / neutral
            xy: tuple[float, float] | None = _dng_white_xy(dng_colour, config)
        else:
            multipliers, xy = _read_libraw_white(path, dng_colour, config)
    except (LibRawError, OSError, ValueError) as err:
        raise DecodeError(f"cannot read {path.name}: {err}") from err
    gain = 2.0**ev if config.baseline_exposure else 1.0
    kelvin, tint = (None, None) if xy is None else xy_to_kelvin_tint(xy)
    return PhotoInfo(
        as_shot_xy=xy,
        as_shot_kelvin=kelvin,
        as_shot_tint=tint,
        baseline_exposure_ev=ev,
        clip_level=clip_level(multipliers, config.highlight_mode, gain),
    )


def _dng_white_xy(colour: DngColour, config: DecodeConfig) -> tuple[float, float]:
    """The as-shot white through the matrix the decode uses for this DNG.

    With ``colour_matrix: libraw`` that is LibRaw's: the last colour matrix (the daylight one)
    alone, without the blend (ADR-0012).
    """
    if config.colour_matrix == "libraw":
        colour = replace(
            colour,
            colour_matrices=colour.colour_matrices[-1:],
            illuminant_kelvin=colour.illuminant_kelvin[-1:],
            forward_matrices=(),
            camera_calibrations=colour.camera_calibrations[-1:],
        )
    return dng_camera_to_working(colour)[1].xy


def _read_libraw_white(
    path: Path, dng_colour: DngColour | None, config: DecodeConfig
) -> tuple[NDArray[np.float64], tuple[float, float] | None]:
    """LibRaw's white-balance multipliers and the as-shot xy (None without a usable matrix)."""
    raw = RawPy()
    try:
        raw.open_file(str(path))
        camera = np.asarray(raw.camera_whitebalance, dtype=np.float64)[:3]
        daylight = np.asarray(raw.daylight_whitebalance, dtype=np.float64)[:3]
        cam_xyz = np.asarray(raw.rgb_xyz_matrix, dtype=np.float64)[:3, :3]
    finally:
        raw.close()
    # LibRaw falls back to its daylight multipliers when the camera recorded none.
    multipliers = camera if np.all(camera > 0) else daylight
    if np.any(cam_xyz) and np.all(multipliers > 0):
        return multipliers, multipliers_to_xy(multipliers, cam_xyz)
    if dng_colour is not None:
        return multipliers, _dng_white_xy(dng_colour, config)
    return multipliers, None


def multipliers_to_xy(
    multipliers: NDArray[np.floating], cam_xyz: NDArray[np.floating]
) -> tuple[float, float]:
    """xy of the white that white-balance ``multipliers`` neutralise.

    The neutral's camera RGB is ``1 / multipliers`` (what the multipliers scale to equal
    channels); ``cam_xyz`` (XYZ → camera RGB) takes it back to XYZ.
    """
    neutral = 1.0 / np.asarray(multipliers, dtype=np.float64)[:3]
    return xyz_to_xy(np.linalg.solve(np.asarray(cam_xyz, dtype=np.float64)[:3, :3], neutral))


def clip_level(multipliers: NDArray[np.floating], highlight_mode: str, gain: float) -> float:
    """The scene-linear value of a white the sensor clipped, after LibRaw's scaling.

    LibRaw scales each raw channel so the white level maps to ``65535 * m_c / norm``, where
    ``m`` are the white-balance multipliers and ``norm`` is their **minimum** with highlight
    mode ``clip`` but their **maximum** otherwise (dcraw's ``scale_colors``). We divide by
    65535, multiply by ``gain`` (``2 ** BaselineExposure``) and apply a matrix that keeps
    white-balanced white at (1, 1, 1), so a neutral surface of camera value ``v`` has all
    three working-space channels at ``gain * v``. What a neutral reaches when the sensor
    saturates depends on the mode:

    - ``clip``: every channel is at least 1 at the white level and is clipped to 1, so the
      clipped white is ``gain``.
    - ``ignore``: channel c stops at ``m_c / max(m)``; a neutral stays neutral only up to
      ``gain * min(m) / max(m)``, then turns magenta. That is the clip level.
    - ``blend``: LibRaw keeps the brightness (channel sum) of the unclipped values and takes
      the colour from the clipped ones, which are equal, so the clipped white is neutral at
      ``gain * mean(m) / max(m)``.
    - ``reconstruct``: the clipped channels are extrapolated from their neighbours and the
      result is clipped at 65535, so whites top out near ``gain`` (measured 0.96 to 1.0 of it).

    Measured with half-size decodes on the CC0 samples with clipped highlights (the maximum
    over pixels of the smallest channel): Fujifilm XQ1 ``clip`` 1.000 (formula 1.000),
    ``blend`` 0.8230 (0.8230); Pentax K-5 IIs ``clip`` 1.4027 (1.4027), ``blend`` 0.9149
    (0.9116: its raw values run 0.8 % past the file's white level, so the brightest channel
    clips at 65535 earlier than the formula assumes).

    This assumes the white level the original specifies. With ``decode.adjust_white_level``
    above 0, LibRaw lowers the white level to the brightest raw value when that is above the
    fraction, and the brightest pixels of a photo without sensor clipping reach this level too
    (off by default, ADR-0018).
    """
    m = np.asarray(multipliers, dtype=np.float64)[:3]
    if highlight_mode == "clip" or highlight_mode == "reconstruct":
        fraction = 1.0
    elif highlight_mode == "ignore":
        fraction = float(m.min() / m.max())
    elif highlight_mode == "blend":
        fraction = float(m.mean() / m.max())
    else:
        raise ValueError(f"unknown highlight mode {highlight_mode!r}")
    return gain * fraction
