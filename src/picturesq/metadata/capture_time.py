"""The capture time an export carries: the camera's, shifted or replaced by the config.

Cameras with an unset clock stamp every photo with a wrong date (the DJI Pocket 4 after a
battery reset says 2000-07-07), and libraries sort by that date. Originals are never
changed, so the correction is config (``metadata``) written into the export's EXIF.

EXIF times carry no zone: they are the local clock's reading. ``OffsetTime*`` tags say
which zone that was.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from PIL.ExifTags import Base

from picturesq.config import ProjectConfig
from picturesq.config.time_shift import parse_time_shift
from picturesq.decode.exif import CaptureExif

EXIF_DATETIME_FORMAT: Final = "%Y:%m:%d %H:%M:%S"
_EXIF_DATETIME_LENGTH: Final = 19
_CAMERA_TIME_TAGS: Final = (Base.DateTimeOriginal, Base.DateTimeDigitized)


class CaptureTimeError(Exception):
    """A shift moves a capture time outside the years 1 to 9999."""


@dataclass(frozen=True)
class CaptureTime:
    """One photo's capture time: as the camera recorded it, and as the export carries it.

    ``camera`` is None when the original records no usable time; then ``corrected`` is None
    too, unless a per-photo capture time supplies one. ``time_zone`` is the offset to write
    (``+01:00``), or None to leave the camera's offset tags alone.
    """

    camera: datetime | None
    corrected: datetime | None
    time_zone: str | None = None

    @property
    def changes_export(self) -> bool:
        """Whether the export's EXIF differs from the camera's."""
        return self.corrected != self.camera or self.time_zone is not None


def parse_exif_datetime(value: object) -> datetime | None:
    """``"2000:07:07 10:00:00"`` -> a datetime; None for anything else (empty, zeroed, odd)."""
    if not isinstance(value, str) or len(value.strip()) < _EXIF_DATETIME_LENGTH:
        return None
    try:
        return datetime.strptime(value.strip()[:_EXIF_DATETIME_LENGTH], EXIF_DATETIME_FORMAT)
    except ValueError:
        return None  # includes 0000:00:00 00:00:00, which cameras write for "unknown"


def format_exif_datetime(value: datetime) -> str:
    """A datetime as EXIF writes it, ``2026:10:17 20:05:00``."""
    return f"{value.year:04d}:{value.month:02d}:{value.day:02d} {value:%H:%M:%S}"


def camera_capture_time(capture: CaptureExif) -> datetime | None:
    """The time the original records: DateTimeOriginal, else DateTimeDigitized, else DateTime."""
    for tag in _CAMERA_TIME_TAGS:
        found = parse_exif_datetime(capture.exif.get(tag))
        if found is not None:
            return found
    return parse_exif_datetime(capture.image.get(Base.DateTime))


def shift_from_reference(camera: datetime, actual: datetime) -> timedelta:
    """The shift that turns ``camera`` (a photo's recorded time) into ``actual`` (the real one)."""
    return actual - camera


def corrected_capture_time(
    camera: datetime | None,
    *,
    shift: timedelta = timedelta(0),
    time_zone: str | None = None,
    override: datetime | None = None,
) -> CaptureTime:
    """The time an export carries. An ``override`` wins; else ``camera`` + ``shift``.

    A photo without a camera time is not shifted (there is nothing to shift).
    """
    if override is not None:
        return CaptureTime(camera, override, time_zone)
    if camera is None:
        return CaptureTime(None, None, time_zone)
    try:
        return CaptureTime(camera, camera + shift, time_zone)
    except OverflowError:
        raise CaptureTimeError(
            f"a shift of {shift} moves {camera:%Y-%m-%d %H:%M:%S} outside the years 1 to 9999"
        ) from None


def photo_capture_time(config: ProjectConfig, name: str, camera: datetime | None) -> CaptureTime:
    """Photo ``name``'s capture time under ``config.metadata`` and the photo's override."""
    return corrected_capture_time(
        camera,
        shift=parse_time_shift(config.metadata.time_shift),
        time_zone=config.metadata.time_zone,
        override=config.photo(name).metadata.capture_time,
    )


def with_capture_time(
    capture: CaptureExif, when: CaptureTime, *, force: bool = False
) -> CaptureExif:
    """``capture`` with the corrected time in DateTimeOriginal, DateTimeDigitized and DateTime
    and, when a zone is set, OffsetTime, OffsetTimeOriginal and OffsetTimeDigitized.

    Unchanged (the same object) when the config changes nothing, so a project without
    ``metadata`` settings exports exactly as before (``force`` writes the dates anyway, to put
    the camera's time back over an earlier correction). Sub-second tags are kept.
    """
    if not (force or when.changes_export):
        return capture
    exif = dict(capture.exif)
    image = dict(capture.image)
    if when.corrected is not None:
        text = format_exif_datetime(when.corrected)
        exif[Base.DateTimeOriginal] = text
        exif[Base.DateTimeDigitized] = text
        image[Base.DateTime] = text
    if when.time_zone is not None:
        for tag in (Base.OffsetTime, Base.OffsetTimeOriginal, Base.OffsetTimeDigitized):
            exif[tag] = when.time_zone
    return CaptureExif(image=image, exif=exif)
