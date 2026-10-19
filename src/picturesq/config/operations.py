"""Operation models: the steps a look file lists, with their parameters (plan §4.3, ADR-0019).

Each operation is a model with an ``op`` name. Every value that sets *how much* an operation
does is declared with :func:`scaled` and has a **neutral value**, the value at which the
operation does nothing. A look's intensity scales each such value between its neutral value
and the look's (:meth:`Operation.scaled`); values that say *where* or *which* (a pivot, a
hue) are kept. The functions that apply operations live in ``picturesq.grade.operations``.
"""

from itertools import pairwise
from typing import Annotated, Any, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator

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


class Scalable(BaseModel):
    """A model whose scaled values intensity moves toward neutral (operations and their parts)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

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
            elif isinstance(value, Scalable):
                update[name] = value.scaled(intensity)
        return self.model_copy(update=update)

    def is_neutral(self) -> bool:
        """Whether every scaled value is at its neutral value: the operation does nothing."""
        for name, info in type(self).model_fields.items():
            value = getattr(self, name)
            neutral = _neutral(info)
            if neutral is not None and value != neutral:
                return False
            if isinstance(value, Scalable) and not value.is_neutral():
                return False
        return True


class Operation(Scalable):
    """One step of a look. Subclasses add an ``op`` literal and their parameters."""

    space: ClassVar[Space] = "scene"


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


class VibranceOperation(Operation):
    """Raise (or lower) the chroma of muted colours more than of colourful ones.

    Oklab chroma ``C`` is scaled by ``1 + amount * (1 - C / VIBRANCE_FULL_CHROMA)``
    (no change at or above that chroma), lightness and hue kept: muted colours and skin
    (chroma ~0.08) gain colour, colours that are already saturated stay as they are.
    """

    op: Literal["vibrance"] = "vibrance"
    amount: float = scaled(
        0.0,
        ge=-1.0,
        le=1.0,
        description="Chroma change for the most muted colours; 0.3 is up to 30 % more.",
    )


VIBRANCE_FULL_CHROMA = 0.25
"""Oklab chroma at and above which vibrance changes nothing (sRGB red is 0.26)."""

HUE_BANDS: dict[str, float] = {
    "red": 25.0,
    "orange": 55.0,
    "yellow": 100.0,
    "green": 140.0,
    "aqua": 195.0,
    "blue": 255.0,
    "purple": 295.0,
    "magenta": 330.0,
}
"""Centre of each hue band, as an Oklab hue angle in degrees. Measured from sRGB colours:
red 29, orange 53, yellow 110, green 143, aqua (cyan) 195, blue 264, purple 294, magenta
328; skin (about 49) falls in orange and sky blue (about 255) in blue."""


class HueBand(Scalable):
    """Changes to one hue band's colours."""

    hue: float = scaled(
        0.0,
        ge=-45.0,
        le=45.0,
        description="Hue shift in degrees (Oklab); + turns red toward yellow, blue toward purple.",
    )
    chroma: float = scaled(
        0.0, ge=-1.0, le=1.0, description="Chroma change; -1 removes the band's colour."
    )
    lightness: float = scaled(
        0.0, ge=-2.0, le=2.0, description="Brightness change in EV (a darker sky: -0.5)."
    )


class HslOperation(Operation):
    """Change hue, chroma and brightness of colours by hue band (Oklab).

    Each pixel belongs to the two bands its hue sits between, weighted smoothly (weights
    sum to 1, so there are no seams). Greys have no hue: the change fades in with chroma
    and is full from ``HSL_FULL_CHROMA``.
    """

    op: Literal["hsl"] = "hsl"
    red: HueBand = Field(default_factory=HueBand)
    orange: HueBand = Field(default_factory=HueBand)
    yellow: HueBand = Field(default_factory=HueBand)
    green: HueBand = Field(default_factory=HueBand)
    aqua: HueBand = Field(default_factory=HueBand)
    blue: HueBand = Field(default_factory=HueBand)
    purple: HueBand = Field(default_factory=HueBand)
    magenta: HueBand = Field(default_factory=HueBand)


HSL_FULL_CHROMA = 0.04
"""Oklab chroma from which a hue band's change applies fully (it fades in from grey)."""


class ToneTint(Scalable):
    """A tint for one end of the tones: the hue it moves toward, and how far."""

    hue: float = Field(default=0.0, ge=0.0, lt=360.0, description="Oklab hue angle, degrees.")
    amount: float = scaled(
        0.0,
        ge=0.0,
        le=1.0,
        description="How strong the tint is; 1 adds 0.1 of Oklab chroma at mid grey.",
    )


class SplitToneOperation(Operation):
    """Tint the shadows toward one hue and the highlights toward another.

    The tint is added in Oklab a/b (lightness kept), in proportion to lightness (so black
    stays black), weighted smoothly by tone: shadows below the crossover, highlights above
    it. The crossover is mid grey, moved by ``balance``.
    """

    op: Literal["split_tone"] = "split_tone"
    shadows: ToneTint = Field(default_factory=ToneTint)
    highlights: ToneTint = Field(default_factory=ToneTint)
    balance: float = Field(
        default=0.0,
        ge=-1.0,
        le=1.0,
        description="Moves the crossover: positive gives the shadows' tint more of the tones.",
    )


SPLIT_TONE_CHROMA = 0.1
"""Oklab chroma that ``amount: 1`` adds at mid grey."""
SPLIT_TONE_WIDTH = 0.25
"""Half the Oklab lightness range over which split toning blends from shadows to
highlights (mid grey is 0.565; black 0, diffuse white 1)."""
SPLIT_TONE_BALANCE = 0.2
"""How far ``balance: 1`` moves the crossover, in Oklab lightness."""

_LUMINANCE_WEIGHTS = (0.2627, 0.6780, 0.0593)
"""Rec.2020 luminance (ITU-R BT.2020's luma coefficients; the working space's Y row to 1e-4)."""


class ChannelMixerOperation(Operation):
    """Black and white by mixing R, G and B into one grey (scene-linear, working space).

    The weights are divided by their sum, so a grey stays the same grey and the overall
    brightness is kept. The defaults are luminance (a neutral conversion); more red darkens
    blue skies and lightens skin, as a red filter does on black and white film. ``amount``
    blends from colour (0) to the mix (1).
    """

    op: Literal["channel_mixer"] = "channel_mixer"
    red: float = Field(default=_LUMINANCE_WEIGHTS[0], ge=-1.0, le=2.0, description="Red weight.")
    green: float = Field(
        default=_LUMINANCE_WEIGHTS[1], ge=-1.0, le=2.0, description="Green weight."
    )
    blue: float = Field(default=_LUMINANCE_WEIGHTS[2], ge=-1.0, le=2.0, description="Blue weight.")
    amount: float = scaled(
        0.0, ge=0.0, le=1.0, description="How far toward black and white; 1 is fully grey."
    )

    @model_validator(mode="after")
    def _weights_sum(self) -> Self:
        if self.red + self.green + self.blue < 0.1:
            raise ValueError("red + green + blue must be at least 0.1 (they are divided by it)")
        return self


class VignetteOperation(Operation):
    """Darken (or lighten) toward the corners, by the same factor on R, G and B.

    Distance is measured from the centre so the corners are at 1; ``roundness`` 1 is a
    circle, 0 an ellipse with the frame's aspect ratio. Nothing changes inside
    ``midpoint``; from there the change eases in to ``amount`` EV at the corners. The same
    at any resolution.
    """

    op: Literal["vignette"] = "vignette"
    amount: float = scaled(
        0.0, ge=-3.0, le=1.0, description="Change at the corners in EV; negative darkens."
    )
    midpoint: float = Field(
        default=0.5, ge=0.0, lt=1.0, description="Distance (corners = 1) where it starts."
    )
    roundness: float = Field(
        default=1.0, ge=0.0, le=1.0, description="1 is a circle, 0 follows the frame's shape."
    )


class GrainOperation(Operation):
    """Film-like grain, display-referred: the same offset on R, G and B (monochrome grain).

    Noise is generated once per photo (seeded from the photo, so it's the same on every
    run) on a grid of ``1 / size`` cells along the long edge, then sampled at each pixel's
    position: proxies, ``web`` and ``archive`` show the same grain pattern at their own
    size. It is strongest in the mid tones and fades out toward black and white, as on
    film.
    """

    space: ClassVar[Space] = "display"
    op: Literal["grain"] = "grain"
    amount: float = scaled(
        0.0,
        ge=0.0,
        le=0.1,
        description="Strength: the noise's standard deviation in the mid tones, as an sRGB value.",
    )
    size: float = Field(
        default=0.0005,
        ge=0.0002,
        le=0.005,
        description="Grain size as a fraction of the long edge (0.0005 is 1/2000).",
    )


LutFile = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*\.cube$")]


class LutOperation(Operation):
    """A ``.cube`` LUT, display-referred, in the colour space it was built for.

    ``file`` is relative to the look file (no ``..``). ``input_space`` says what the LUT
    expects and returns: ``srgb`` (sRGB primaries and curve, what most creative LUTs are
    made for) or ``rec709`` (Rec.709 primaries, BT.1886 gamma 2.4). The display transform's
    output is encoded into that space, looked up, and decoded back. ``amount`` blends the
    LUT's result with its input: intensity scales it like any strength value. The table is
    loaded with the look file (``picturesq.config.look``).
    """

    space: ClassVar[Space] = "display"
    op: Literal["lut"] = "lut"
    file: LutFile = Field(description="The .cube file, relative to the look file.")
    input_space: Literal["srgb", "rec709"] = Field(
        default="srgb", description="What the LUT expects: srgb or rec709 (gamma 2.4)."
    )
    amount: float = scaled(
        0.0,
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Blend of the LUT's result with its input; 1 is the LUT as made.",
    )
    _table: Any = PrivateAttr(default=None)

    @field_validator("file")
    @classmethod
    def _inside(cls, file: str) -> str:
        if any(part in ("", ".", "..") for part in file.split("/")):
            raise ValueError("file must be a path inside the look's folder (no . or ..)")
        return file

    @property
    def table(self) -> Any:
        """The loaded LUT (``picturesq.colour.lut.Lut``), or None before loading."""
        return self._table

    def with_table(self, table: Any) -> Self:
        """This operation with its LUT loaded."""
        loaded = self.model_copy()
        loaded._table = table
        return loaded


AnyOperation = Annotated[
    ExposureOperation
    | WhiteBalanceOperation
    | ContrastOperation
    | SaturationOperation
    | ToneCurveOperation
    | FadeOperation
    | VibranceOperation
    | HslOperation
    | SplitToneOperation
    | ChannelMixerOperation
    | VignetteOperation
    | GrainOperation
    | LutOperation,
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
    VibranceOperation,
    HslOperation,
    SplitToneOperation,
    ChannelMixerOperation,
    VignetteOperation,
    GrainOperation,
    LutOperation,
)
