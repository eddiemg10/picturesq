"""Operation models: the steps a look file lists, with their parameters (plan §4.3, ADR-0019).

Each operation is a model with an ``op`` name. Every value that sets *how much* an operation
does is declared with :func:`scaled` and has a **neutral value**, the value at which the
operation does nothing. A look's intensity scales each such value between its neutral value
and the look's (:meth:`Operation.scaled`); values that say *where* or *which* (a pivot, a
hue) are kept. The functions that apply operations live in ``picturesq.grade.operations``.
"""

from itertools import pairwise
from typing import Annotated, Any, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

from picturesq.colour.transfer import MIDDLE_GREY

MAX_INTENSITY = 1.5
"""Highest intensity a look can be applied at (150 %)."""

Space = Literal["scene", "display"]
"""Where an operation runs: on scene-linear values, or display-referred after the display
transform."""


def scaled(neutral: float = 0.0, **field: Any) -> Any:
    """A ``Field`` that intensity scales toward ``neutral``, its default unless ``default``
    is given. Takes ``Field``'s arguments."""
    default = field.pop("default", neutral)
    return Field(default=default, json_schema_extra={"neutral": neutral}, **field)


def _neutral(info: Any) -> float | None:
    extra = info.json_schema_extra
    if isinstance(extra, dict):
        value = extra.get("neutral")
        if isinstance(value, int | float):
            return float(value)
    return None


class Operation(BaseModel):
    """One step of a look. Subclasses add an ``op`` literal and their parameters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    space: ClassVar[Space] = "scene"

    def scaled(self, intensity: float) -> Self:
        """This operation at ``intensity``: each scaled value becomes
        ``neutral + intensity * (value - neutral)``, other values are kept.

        The result skips validation: at intensities above 1 a value may pass its declared
        range, so each operation's function keeps its maths sane (e.g. no negative chroma).
        """
        update: dict[str, object] = {}
        for name, info in type(self).model_fields.items():
            value = getattr(self, name)
            neutral = _neutral(info)
            if neutral is not None:
                update[name] = neutral + intensity * (value - neutral)
            elif isinstance(value, Operation):
                update[name] = value.scaled(intensity)
        return self.model_copy(update=update)

    def is_neutral(self) -> bool:
        """Whether every scaled value is at its neutral value: the operation does nothing."""
        for name, info in type(self).model_fields.items():
            value = getattr(self, name)
            neutral = _neutral(info)
            if neutral is not None and value != neutral:
                return False
            if isinstance(value, Operation) and not value.is_neutral():
                return False
        return True


class ExposureOperation(Operation):
    """Brighten or darken: every channel times ``2**ev``."""

    op: Literal["exposure"] = "exposure"
    ev: float = scaled(0.0, ge=-4.0, le=4.0, description="Exposure change in EV (stops).")


class WhiteBalanceOperation(Operation):
    """Warm or cool the photo, and shift it toward magenta or green.

    Re-balances as if the light had been ``warmth`` mired bluer than daylight (D65) and
    ``tint`` greener, by chromatic adaptation in scene-linear: positive warmth makes the
    photo warmer, positive tint more magenta. Equal mired steps look about equally strong
    at any colour temperature.
    """

    op: Literal["white_balance"] = "white_balance"
    warmth: float = scaled(
        0.0, ge=-100.0, le=100.0, description="Warmth in mired; positive is warmer (yellower)."
    )
    tint: float = scaled(
        0.0,
        ge=-50.0,
        le=50.0,
        description="Tint on the normalise scale (-1000 x Duv); positive is magenta.",
    )


class ContrastOperation(Operation):
    """More or less contrast around a pivot, in log space, keeping colour ratios.

    Luminance ``Y`` becomes ``pivot * (Y / pivot)**(1 + amount)``: each stop away from the
    pivot becomes ``1 + amount`` stops, the same in the shadows and the highlights. R, G
    and B get the same gain, so hue and saturation are kept.
    """

    op: Literal["contrast"] = "contrast"
    amount: float = scaled(
        0.0, ge=-0.9, le=1.0, description="Extra contrast; 0.2 makes tones 20 % steeper in EV."
    )
    pivot: float = Field(
        default=MIDDLE_GREY,
        gt=0.0,
        le=1.0,
        description="Scene-linear luminance that stays put (0.18 is mid grey).",
    )


class SaturationOperation(Operation):
    """Scale every pixel's chroma (Oklab), keeping its lightness and hue."""

    op: Literal["saturation"] = "saturation"
    amount: float = scaled(
        0.0, ge=-1.0, le=1.0, description="Chroma change; -1 is greyscale, 0.2 is 20 % more."
    )


MAX_CURVE_EV = 12.0
"""Furthest a tone curve point may be from mid grey, in EV."""

CurvePoint = tuple[
    Annotated[float, Field(ge=-MAX_CURVE_EV, le=MAX_CURVE_EV)],
    Annotated[float, Field(ge=-MAX_CURVE_EV, le=MAX_CURVE_EV)],
]


class ToneCurveOperation(Operation):
    """Bend brightness with a smooth curve through a few points, keeping colour ratios.

    Each point is ``[input, output]`` in EV of luminance relative to mid grey (0.18):
    ``[2, 1.5]`` puts what was 2 stops above mid grey 1.5 stops above it (softer
    highlights). The curve is monotone cubic (no overshoot between points); beyond the
    first and last points it continues straight, at the slope between the two end points,
    so softened highlights stay soft. Intensity moves each point's output toward its input
    (the identity, the neutral curve). Scene-linear, before the display transform, which
    still rolls highlights off.
    """

    op: Literal["tone_curve"] = "tone_curve"
    points: tuple[CurvePoint, ...] = Field(
        default=(),
        max_length=16,
        description=(
            "[input, output] pairs in EV relative to mid grey, inputs increasing, outputs "
            "not decreasing. Empty (or every output equal to its input) is the identity."
        ),
    )

    @field_validator("points")
    @classmethod
    def _monotone(cls, points: tuple[CurvePoint, ...]) -> tuple[CurvePoint, ...]:
        inputs = [x for x, _ in points]
        outputs = [y for _, y in points]
        if any(b <= a for a, b in pairwise(inputs)):
            raise ValueError("point inputs must increase")
        if any(b < a for a, b in pairwise(outputs)):
            raise ValueError("point outputs must not decrease (tones would swap order)")
        return points

    def scaled(self, intensity: float) -> Self:
        points = tuple((x, x + intensity * (y - x)) for x, y in self.points)
        return self.model_copy(update={"points": points})

    def is_neutral(self) -> bool:
        return all(x == y for x, y in self.points)


class FadeOperation(Operation):
    """Lift the blacks toward grey, the matte look of faded film or prints.

    Display-referred, a *lift* as in grading tools: on sRGB-encoded values ``e``,
    ``e + amount * (1 - e)``. Black becomes ``amount`` (0.05 is 13 of 255), white stays
    white, and the change fades out toward white: mid grey goes from 0.46 to 0.49 at 0.05.
    """

    space: ClassVar[Space] = "display"
    op: Literal["fade"] = "fade"
    amount: float = scaled(
        0.0, ge=0.0, le=0.3, description="Where black ends up, as an sRGB value (0 to 1)."
    )


AnyOperation = Annotated[
    ExposureOperation
    | WhiteBalanceOperation
    | ContrastOperation
    | SaturationOperation
    | ToneCurveOperation
    | FadeOperation,
    Field(discriminator="op"),
]
"""Any operation, chosen by its ``op`` name (for look files)."""

OPERATION_TYPES: tuple[type[Operation], ...] = (
    ExposureOperation,
    WhiteBalanceOperation,
    ContrastOperation,
    SaturationOperation,
    ToneCurveOperation,
    FadeOperation,
)
