"""Project config model: the contents of ``<project>/picturesq.yaml``.

v0 holds the decode, normalise (exposure, chroma noise reduction), grade (display transform
only) and export sections. Looks, adjustments and per-photo overrides are added in the
milestones that implement them, so the config never offers a setting the pipeline ignores.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from picturesq.colour.transfer import SRGB_GREY_ENCODED, SRGB_GREY_SLOPE_PER_EV

CONFIG_FILENAME = "picturesq.yaml"

OutputName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]


class _Model(BaseModel):
    # Unknown keys are errors: a typo must not silently fall back to a default.
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class DecodeConfig(_Model):
    """Stage 1 settings, passed to LibRaw. The demosaic default is finalised in #15."""

    demosaic: Literal["linear", "vng", "ppg", "ahd", "dcb", "dht", "aahd"] = Field(
        default="ahd", description="Demosaic algorithm (LibRaw)."
    )
    highlight_mode: Literal["clip", "ignore", "blend", "reconstruct"] = Field(
        default="blend", description="How LibRaw treats clipped sensor highlights."
    )
    baseline_exposure: bool = Field(
        default=True,
        description=(
            "Apply the DNG BaselineExposure tag (brightening the camera's deliberate "
            "underexposure)."
        ),
    )


Fraction = Annotated[float, Field(ge=0.0, lt=1.0)]


class ExposureConfig(_Model):
    """One global exposure change per photo (ADR-0010)."""

    offset_ev: float = Field(
        default=2.0,
        ge=-4.0,
        le=6.0,
        description=(
            "Brightening applied to every photo, in EV. Cameras render about 2 EV brighter than "
            "the raw's own exposure; fitted to camera JPEGs."
        ),
    )
    correction: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "How far each photo's median brightness is pulled toward target_ev (0 = off, "
            "1 = all the way). Evens out a batch; cameras don't do it."
        ),
    )
    target_ev: float = Field(
        default=-1.0,
        ge=-6.0,
        le=3.0,
        description="Median brightness that correction pulls toward, in EV relative to mid grey.",
    )
    max_correction_ev: float = Field(
        default=2.0, ge=0.0, le=6.0, description="Largest change correction may make, in EV."
    )


class ChromaNoiseReductionConfig(_Model):
    """Colour noise reduction in the shadows (Oklab a/b blur)."""

    amount: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Strength in the darkest tones; 0 turns it off."
    )
    radius: float = Field(
        default=0.004,
        gt=0.0,
        le=0.05,
        description="Blur radius as a fraction of the photo's long edge (0.004 = 31 px at 7680).",
    )
    full_lightness: float = Field(
        default=0.35,
        ge=0.0,
        lt=1.0,
        description="Oklab lightness up to which the full amount applies (0.35 ≈ 3 EV below grey).",
    )
    fade_lightness: float = Field(
        default=0.6,
        gt=0.0,
        le=1.0,
        description="Oklab lightness at which it has faded out (0.6 ≈ mid grey and above).",
    )

    @model_validator(mode="after")
    def _fade_above_full(self) -> "ChromaNoiseReductionConfig":
        if self.fade_lightness <= self.full_lightness:
            raise ValueError("fade_lightness must be greater than full_lightness")
        return self


class NormaliseConfig(_Model):
    """Stage 2 settings: per-photo exposure and noise reduction."""

    enabled: bool = Field(default=True, description="Run the normalise stage.")
    exposure: ExposureConfig = Field(default_factory=ExposureConfig)
    chroma_nr: ChromaNoiseReductionConfig = Field(default_factory=ChromaNoiseReductionConfig)


class DisplayTransformConfig(_Model):
    """The AgX-style display transform (ADR-0003): inset → log encode → sigmoid → outset.

    Defaults are our own (ADR-0007), not copied from another implementation: contrast 1.0 and
    toe 1.5 keep shadows at least as bright as a plain sRGB view of the linear image (higher
    contrast crushed the 2-6 EV below mid grey where most of an unnormalised photo sits);
    inset and outset by measuring Oklab hue drift on saturated exposure ramps
    (less inset drifts more, more inset desaturates).
    """

    min_ev: float = Field(
        default=-10.0, lt=0.0, description="Scene EV (relative to mid grey) that maps to black."
    )
    max_ev: float = Field(
        default=9.0, gt=0.0, description="Scene EV (relative to mid grey) that maps to white."
    )
    contrast: float = Field(
        default=1.3,
        gt=0.0,
        description="Midtone contrast; 1.0 matches the slope of the plain sRGB curve at mid grey.",
    )
    toe: float = Field(
        default=2.1,
        gt=0.0,
        le=10.0,
        description="Toe sharpness; higher keeps shadows linear longer.",
    )
    shoulder: float = Field(
        default=2.1,
        gt=0.0,
        le=10.0,
        description=(
            "Shoulder sharpness; higher keeps highlights linear longer, then rolls off harder."
        ),
    )
    inset: tuple[Fraction, Fraction, Fraction] = Field(
        default=(0.25, 0.25, 0.25),
        description="How far each primary (R, G, B) is pulled toward white before the curve.",
    )
    chroma_preservation: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description=(
            "Blend toward a render that keeps each pixel's colour ratios: 0 is pure per-channel "
            "AgX (bright colours wash out toward white), 1 keeps highlights fully saturated."
        ),
    )
    saturation: float = Field(
        default=1.25, ge=0.0, le=3.0, description="Overall chroma scale after the curve; 1 is none."
    )
    saturation_fade: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description=(
            "How much of the saturation change fades out toward white: 1 = none left at white, "
            "0 = the same everywhere."
        ),
    )
    outset: tuple[Fraction, Fraction, Fraction] = Field(
        default=(0.35, 0.35, 0.35),
        description="How much saturation each primary (R, G, B) gets back after the curve.",
    )

    @model_validator(mode="after")
    def _curve_reaches_black_and_white(self) -> "DisplayTransformConfig":
        # The sigmoid starts at mid grey with the given slope and bends to reach (0, 0) and
        # (1, 1); it can only bend *away* from the straight line, so the slope must be
        # steeper than the line from mid grey to each corner.
        slope = self.contrast * SRGB_GREY_SLOPE_PER_EV
        if slope * self.max_ev <= 1.0 - SRGB_GREY_ENCODED:
            raise ValueError("contrast is too low for max_ev: raise contrast or max_ev")
        if slope * -self.min_ev <= SRGB_GREY_ENCODED:
            raise ValueError("contrast is too low for min_ev: raise contrast or lower min_ev")
        return self


class GradeConfig(_Model):
    """Stage 3 settings. v0: the display transform only; looks and adjustments come in M3."""

    display_transform: DisplayTransformConfig = Field(default_factory=DisplayTransformConfig)


class SharpenConfig(_Model):
    """Unsharp mask on lightness, at the output's size (after resizing)."""

    amount: float = Field(
        default=0.5, ge=0.0, le=3.0, description="Strength; 0 turns sharpening off."
    )
    radius: float = Field(default=0.8, gt=0.0, le=5.0, description="Blur radius in output pixels.")


class OutputConfig(_Model):
    """One export target, e.g. ``web`` or ``archive``."""

    long_edge: int | None = Field(
        default=None, gt=0, description="Long edge in pixels; null keeps the full resolution."
    )
    quality: int = Field(default=90, ge=1, le=100, description="JPEG quality.")
    sharpen: SharpenConfig = Field(default_factory=SharpenConfig)


def _default_outputs() -> dict[str, OutputConfig]:
    return {
        "web": OutputConfig(
            long_edge=2048, quality=90, sharpen=SharpenConfig(amount=0.5, radius=0.8)
        ),
        "archive": OutputConfig(
            long_edge=None, quality=95, sharpen=SharpenConfig(amount=0.3, radius=1.2)
        ),
    }


class ExportConfig(_Model):
    """Stage 4 settings: the named outputs and which of them run."""

    outputs: dict[OutputName, OutputConfig] = Field(default_factory=_default_outputs)
    enabled: list[OutputName] = Field(
        default_factory=lambda: ["web", "archive"],
        description="Outputs written by `picturesq export`, in order.",
    )

    @model_validator(mode="after")
    def _enabled_outputs_exist(self) -> "ExportConfig":
        unknown = [name for name in self.enabled if name not in self.outputs]
        if unknown:
            raise ValueError(
                f"enabled lists unknown outputs {unknown}; defined: {sorted(self.outputs)}"
            )
        if len(set(self.enabled)) != len(self.enabled):
            raise ValueError("enabled lists an output more than once")
        return self


class ProjectConfig(_Model):
    """Everything in ``picturesq.yaml``. All sections have defaults, so ``{}`` is valid."""

    version: Literal[1] = Field(default=1, description="Config format version.")
    decode: DecodeConfig = Field(default_factory=DecodeConfig)
    normalise: NormaliseConfig = Field(default_factory=NormaliseConfig)
    grade: GradeConfig = Field(default_factory=GradeConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)
