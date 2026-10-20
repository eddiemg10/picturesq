"""Time shifts as written in ``picturesq.yaml``: ``+9598d 10:05:00``.

A signed number of days, then hours:minutes:seconds, exact to the second. Always one form
(sign and days included), so a shift read from a file and written back is unchanged. The
command line also accepts the compact form ``-1d2h30m`` for ``picturesq metadata shift --by``.
"""

import re
from datetime import timedelta
from typing import Final

_CANONICAL: Final = re.compile(r"^([+-])(\d+)d ([01]\d|2[0-3]):([0-5]\d):([0-5]\d)$")
_COMPACT: Final = re.compile(r"^([+-])?(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")
_SECONDS_PER_DAY: Final = 86_400

TIME_SHIFT_PATTERN: Final = r"^[+-]\d+d ([01]\d|2[0-3]):[0-5]\d:[0-5]\d$"
"""The JSON Schema pattern of a shift."""


def format_time_shift(shift: timedelta) -> str:
    """``timedelta(days=1, hours=2)`` -> ``+1d 02:00:00``. Whole seconds only."""
    if shift.microseconds:
        raise ValueError("a time shift is a whole number of seconds")
    total = abs(shift.days * _SECONDS_PER_DAY + shift.seconds)
    days, rest = divmod(total, _SECONDS_PER_DAY)
    hours, rest = divmod(rest, 3600)
    minutes, seconds = divmod(rest, 60)
    sign = "-" if shift < timedelta(0) else "+"
    return f"{sign}{days}d {hours:02d}:{minutes:02d}:{seconds:02d}"


def parse_time_shift(text: str) -> timedelta:
    """``+9598d 10:05:00`` -> a timedelta. Raises ValueError on any other form."""
    match = _CANONICAL.match(text)
    if match is None:
        raise ValueError(
            f"{text!r} is not a time shift; write it as a sign, days, then hours:minutes:seconds "
            "(e.g. +9598d 10:05:00 or -0d 01:00:00)"
        )
    sign, days, hours, minutes, seconds = match.groups()
    shift = timedelta(days=int(days), hours=int(hours), minutes=int(minutes), seconds=int(seconds))
    return -shift if sign == "-" else shift


def parse_compact_shift(text: str) -> timedelta:
    """``-1d2h30m`` or ``+90m`` -> a timedelta (the canonical form is accepted too)."""
    if ":" in text:
        return parse_time_shift(text.strip())
    match = _COMPACT.match(text.strip().replace(" ", ""))
    if match is None or not any(match.groups()[1:]):
        raise ValueError(
            f"{text!r} is not a time shift; write it like -1d2h30m, +90m or +9598d 10:05:00"
        )
    sign, days, hours, minutes, seconds = match.groups()
    shift = timedelta(
        days=int(days or 0),
        hours=int(hours or 0),
        minutes=int(minutes or 0),
        seconds=int(seconds or 0),
    )
    return -shift if sign == "-" else shift
