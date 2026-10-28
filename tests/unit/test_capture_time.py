"""Capture time correction: shift maths, config round trip, EXIF tags."""

from datetime import datetime, timedelta

import pytest
import yaml
from PIL.ExifTags import Base
from pydantic import ValidationError

from picturesq.config import ProjectConfig, dump_project_config
from picturesq.config.time_shift import (
    format_time_shift,
    parse_compact_shift,
    parse_time_shift,
)
from picturesq.decode import CaptureExif
from picturesq.metadata import (
    CaptureTime,
    CaptureTimeError,
    camera_capture_time,
    corrected_capture_time,
    format_exif_datetime,
    parse_clock_time,
    parse_exif_datetime,
    photo_capture_time,
    shift_from_reference,
    with_capture_time,
)

CAMERA = datetime(2000, 7, 7, 10, 0, 0)


@pytest.mark.parametrize(
    ("camera", "shift", "expected"),
    [
        (CAMERA, timedelta(0), CAMERA),
        (datetime(2000, 1, 31, 23, 30), timedelta(hours=1), datetime(2000, 2, 1, 0, 30)),
        (datetime(1999, 12, 31, 23, 59, 59), timedelta(seconds=1), datetime(2000, 1, 1)),
        (datetime(2000, 2, 28, 12), timedelta(days=1), datetime(2000, 2, 29, 12)),  # leap year
        (datetime(2001, 2, 28, 12), timedelta(days=1), datetime(2001, 3, 1, 12)),  # not one
        (datetime(2000, 3, 1, 0, 0), timedelta(seconds=-1), datetime(2000, 2, 29, 23, 59, 59)),
        (datetime(2000, 1, 1), timedelta(days=-1), datetime(1999, 12, 31)),
        (CAMERA, timedelta(days=9598, hours=10, minutes=5), datetime(2026, 10, 17, 20, 5)),
    ],
)
def test_shift_moves_the_camera_time(
    camera: datetime, shift: timedelta, expected: datetime
) -> None:
    assert corrected_capture_time(camera, shift=shift).corrected == expected


def test_no_shift_leaves_the_time_unchanged() -> None:
    when = corrected_capture_time(CAMERA)
    assert when == CaptureTime(CAMERA, CAMERA, None)
    assert not when.changes_export


def test_override_wins_over_the_shift() -> None:
    actual = datetime(2026, 10, 17, 20, 5)
    when = corrected_capture_time(CAMERA, shift=timedelta(days=5), override=actual)
    assert when.corrected == actual
    assert when.camera == CAMERA


def test_photo_without_a_camera_time_is_not_shifted() -> None:
    assert corrected_capture_time(None, shift=timedelta(days=5)).corrected is None
    actual = datetime(2026, 10, 17, 20, 5)
    assert corrected_capture_time(None, override=actual).corrected == actual


def test_how_says_where_the_corrected_time_comes_from() -> None:
    actual = datetime(2026, 10, 17, 20, 5)
    assert corrected_capture_time(CAMERA).how == "unchanged"
    assert corrected_capture_time(CAMERA, shift=timedelta(hours=1)).how == "shifted"
    assert corrected_capture_time(CAMERA, override=actual).how == "set for this photo"
    assert corrected_capture_time(CAMERA, override=CAMERA).how == "set for this photo"
    assert corrected_capture_time(None, shift=timedelta(hours=1)).how == "no time recorded"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-10-17 20:05", datetime(2026, 10, 17, 20, 5)),
        ("2026-10-17T20:05:09", datetime(2026, 10, 17, 20, 5, 9)),
        (" 2026-10-17T20:05:09.5 ", datetime(2026, 10, 17, 20, 5, 9)),
    ],
)
def test_parse_clock_time(text: str, expected: datetime) -> None:
    assert parse_clock_time(text) == expected


@pytest.mark.parametrize("text", ["yesterday", "2026-10-17T20:05+01:00", ""])
def test_parse_clock_time_refuses_anything_else(text: str) -> None:
    with pytest.raises(ValueError):
        parse_clock_time(text)


def test_shift_out_of_range_is_an_error() -> None:
    with pytest.raises(CaptureTimeError, match="outside the years"):
        corrected_capture_time(datetime(9999, 12, 31), shift=timedelta(days=1))


@pytest.mark.parametrize("actual", [datetime(2026, 10, 17, 20, 5), datetime(1999, 1, 1)])
def test_shift_from_reference_round_trips(actual: datetime) -> None:
    shift = shift_from_reference(CAMERA, actual)
    assert corrected_capture_time(CAMERA, shift=shift).corrected == actual


@pytest.mark.parametrize(
    "shift",
    [
        timedelta(0),
        timedelta(days=9598, hours=10, minutes=5),
        timedelta(days=-1, hours=-2, seconds=-3),
        timedelta(seconds=-1),
        timedelta(hours=23, minutes=59, seconds=59),
    ],
)
def test_time_shift_text_round_trips(shift: timedelta) -> None:
    assert parse_time_shift(format_time_shift(shift)) == shift


def test_time_shift_text_format() -> None:
    assert format_time_shift(timedelta(days=9598, hours=10, minutes=5)) == "+9598d 10:05:00"
    assert format_time_shift(timedelta(hours=-1)) == "-0d 01:00:00"
    assert format_time_shift(timedelta(0)) == "+0d 00:00:00"
    assert parse_time_shift("-0d 01:00:00") == timedelta(hours=-1)


@pytest.mark.parametrize("text", ["", "1d", "+1d 24:00:00", "+1d 1:00:00", "1d 01:00:00", "+1 day"])
def test_time_shift_text_rejects_other_forms(text: str) -> None:
    with pytest.raises(ValueError, match="time shift"):
        parse_time_shift(text)


def test_time_shift_with_fractions_of_a_second_is_refused() -> None:
    with pytest.raises(ValueError, match="whole number of seconds"):
        format_time_shift(timedelta(milliseconds=1))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("+1h", timedelta(hours=1)),
        ("-1d2h30m", -timedelta(days=1, hours=2, minutes=30)),
        ("90m", timedelta(minutes=90)),
        ("+1d 2h", timedelta(days=1, hours=2)),
        ("+9598d 10:05:00", timedelta(days=9598, hours=10, minutes=5)),
    ],
)
def test_compact_shift(text: str, expected: timedelta) -> None:
    assert parse_compact_shift(text) == expected


@pytest.mark.parametrize("text", ["", "+", "soon", "1x"])
def test_compact_shift_rejects_nonsense(text: str) -> None:
    with pytest.raises(ValueError, match="time shift"):
        parse_compact_shift(text)


def test_exif_datetime_parsing() -> None:
    assert parse_exif_datetime("2000:07:07 10:00:00") == CAMERA
    assert parse_exif_datetime("2000:07:07 10:00:00\x00") == CAMERA
    for bad in ("0000:00:00 00:00:00", "", "   :  :     :  :  ", "2000:13:07 10:00:00", None, 5):
        assert parse_exif_datetime(bad) is None
    assert format_exif_datetime(datetime(5, 1, 2, 3, 4, 5)) == "0005:01:02 03:04:05"


def test_camera_time_prefers_original_then_digitized_then_datetime() -> None:
    original = "2000:07:07 10:00:00"
    other = "2001:01:01 01:01:01"
    both = CaptureExif(
        image={Base.DateTime: other},
        exif={Base.DateTimeOriginal: original, Base.DateTimeDigitized: other},
    )
    assert camera_capture_time(both) == CAMERA
    digitized = CaptureExif(image={Base.DateTime: other}, exif={Base.DateTimeDigitized: original})
    assert camera_capture_time(digitized) == CAMERA
    assert camera_capture_time(CaptureExif(image={Base.DateTime: original})) == CAMERA
    assert camera_capture_time(CaptureExif()) is None


def test_config_defaults_change_nothing() -> None:
    config = ProjectConfig()
    when = photo_capture_time(config, "a.dng", CAMERA)
    capture = CaptureExif(exif={Base.DateTimeOriginal: "2000:07:07 10:00:00"})
    assert with_capture_time(capture, when) is capture


def test_config_round_trips_and_drops_unset_overrides() -> None:
    config = ProjectConfig.model_validate(
        {
            "metadata": {"time_shift": "+9598d 10:05:00", "time_zone": "+01:00"},
            "photos": {
                "a.dng": {"metadata": {"capture_time": "2026-10-17 20:05"}},
            },
        }
    )
    assert config.photo("A.DNG").metadata.capture_time == datetime(2026, 10, 17, 20, 5)
    text = dump_project_config(config)
    assert ProjectConfig.model_validate(yaml.safe_load(text)) == config
    photos = yaml.safe_load(text)["photos"]
    assert photos == {"a.dng": {"metadata": {"capture_time": "2026-10-17T20:05:00"}}}


def test_unquoted_yaml_datetime_is_accepted() -> None:
    config = ProjectConfig.model_validate(
        yaml.safe_load("photos:\n  a.dng:\n    metadata: {capture_time: 2026-10-17T20:05:00}\n")
    )
    assert config.photo("a.dng").metadata.capture_time == datetime(2026, 10, 17, 20, 5)


@pytest.mark.parametrize(
    "data",
    [
        {"metadata": {"time_shift": "1 day"}},
        {"metadata": {"time_zone": "BST"}},
        {"metadata": {"time_zone": "+15:00"}},
        {"metadata": {"time_zone": "+01:75"}},
        {"metadata": {"zone": "+01:00"}},
        {"photos": {"a.dng": {"metadata": {"capture_time": "2026-10-17T20:05:00+01:00"}}}},
        {"photos": {"a.dng": {"metadata": {"capture_time": "yesterday"}}}},
    ],
)
def test_config_rejects_bad_metadata(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate(data)


def test_photo_capture_time_uses_the_project_and_the_photo() -> None:
    config = ProjectConfig.model_validate(
        {
            "metadata": {"time_shift": "-0d 01:00:00", "time_zone": "+02:00"},
            "photos": {"b.dng": {"metadata": {"capture_time": "2026-10-17T20:05:00"}}},
        }
    )
    shifted = photo_capture_time(config, "a.dng", CAMERA)
    assert shifted == CaptureTime(CAMERA, datetime(2000, 7, 7, 9), "+02:00")
    assert photo_capture_time(config, "B.DNG", CAMERA).corrected == datetime(2026, 10, 17, 20, 5)


def test_with_capture_time_writes_every_date_and_offset_tag() -> None:
    capture = CaptureExif(
        image={Base.Make: "DJI", Base.DateTime: "2000:07:07 10:00:00"},
        exif={
            Base.DateTimeOriginal: "2000:07:07 10:00:00",
            Base.DateTimeDigitized: "2000:07:07 10:00:00",
            Base.SubsecTimeOriginal: "123",
            Base.ISOSpeedRatings: 100,
        },
    )
    when = CaptureTime(CAMERA, datetime(2026, 10, 17, 20, 5, 1), "+01:00")
    result = with_capture_time(capture, when)
    assert result.image == {Base.Make: "DJI", Base.DateTime: "2026:10:17 20:05:01"}
    assert result.exif[Base.DateTimeOriginal] == "2026:10:17 20:05:01"
    assert result.exif[Base.DateTimeDigitized] == "2026:10:17 20:05:01"
    for tag in (Base.OffsetTime, Base.OffsetTimeOriginal, Base.OffsetTimeDigitized):
        assert result.exif[tag] == "+01:00"
    assert result.exif[Base.SubsecTimeOriginal] == "123"
    assert result.exif[Base.ISOSpeedRatings] == 100
    assert capture.exif[Base.DateTimeOriginal] == "2000:07:07 10:00:00"  # the input is untouched


def test_zone_alone_writes_offsets_and_keeps_the_dates() -> None:
    capture = CaptureExif(exif={Base.DateTimeOriginal: "2000:07:07 10:00:00"})
    result = with_capture_time(capture, corrected_capture_time(CAMERA, time_zone="-05:00"))
    assert result.exif[Base.DateTimeOriginal] == "2000:07:07 10:00:00"
    assert result.exif[Base.OffsetTimeOriginal] == "-05:00"
    assert result.image[Base.DateTime] == "2000:07:07 10:00:00"
