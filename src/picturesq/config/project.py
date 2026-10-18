"""Project config model: the contents of ``<project>/picturesq.yaml``.

v0 holds the decode, normalise (exposure, chroma noise reduction, white balance check,
outlier ranges), grade (display transform only), export and per-photo override sections.
Looks and adjustments are added in the milestones that implement them, so the config never
offers a setting the pipeline ignores.
"""

from typing import Annotated, Final, Literal

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
    colour_matrix: Literal["dng", "libraw"] = Field(
        default="dng",
        description=(
            "Camera colour matrix. 'dng': as the DNG specification says, blending the file's "
            "two colour matrices by the photo's white balance (ADR-0012); 'libraw': LibRaw's "
            "matrix (always the daylight one). Non-DNG RAWs always use LibRaw's."
        ),
    )
    lens_corrections: bool = Field(
        default=False,
        description=(
            "Apply the lens corrections a DNG carries (OpcodeList3: vignetting gain maps, "
            "distortion and lateral chromatic aberration warps). Experimental: follows the "
            "DNG spec but is not yet verified against a reference render."
        ),
    )
    default_crop: bool = Field(
        default=True,
        description=(
            "Crop to the photo's frame as the original specifies it (the DNG DefaultCrop, "
            "or the maker's equivalent): drops sensor border pixels, and the strips outside "
            "the aspect ratio the camera was set to (e.g. 3:2 on a 4:3 sensor)."
        ),
    )
    baseline_exposure: bool = Field(
        default=True,
        description=(
            "Apply the DNG BaselineExposure tag (brightening the camera's deliberate "
            "underexposure)."
        ),
    )
    proxy_long_edge: int = Field(
        default=2048,
        ge=256,
        le=8192,
        description=(
            "Long edge of the cached proxy (pixels) used by previews and the UI. Proxies are "
            "never upscaled. Changing it rebuilds the cache."
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
    """Colour noise reduction in the shadows (smooths chromaticity, keeps luminance)."""

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
        default=0.2,
        ge=0.0,
        lt=1.0,
        description=(
            "Lightness (cube root of luminance, as Oklab L for greys) up to which the full "
            "amount applies; 0.2 is 4.5 EV below mid grey."
        ),
    )
    fade_lightness: float = Field(
        default=0.4,
        gt=0.0,
        le=1.0,
        description="Lightness at which it has faded out (0.4 is about 1.5 EV below mid grey).",
    )

    @model_validator(mode="after")
    def _fade_above_full(self) -> "ChromaNoiseReductionConfig":
        if self.fade_lightness <= self.full_lightness:
            raise ValueError("fade_lightness must be greater than full_lightness")
        return self


class WhiteBalanceConfig(_Model):
    """The white balance check: compare the as-shot white balance with an estimate.

    Normalise keeps the camera's as-shot white balance; when both estimates from the photo
    itself (``brightest`` and ``grey``) differ from it by at least ``flag_disagreement_mired``
    in the same direction, the photo gets the ``wb_disagreement`` flag. Nothing is changed
    automatically (plan D6). See :mod:`picturesq.normalise.white_balance_check` for the
    measurements behind the default.
    """

    flag_disagreement_mired: float = Field(
        default=30.0,
        gt=0.0,
        le=500.0,
        description=(
            "Flag a photo when both white balance estimates differ from the as-shot one by at "
            "least this, the same way, in mired (30 is about 600 K near 4500 K, 1100 K near "
            "6500 K)."
        ),
    )


class OutliersConfig(_Model):
    """Ranges a photo's stats should fall in after normalise; outside one, it is an outlier.

    An outlier is flagged, never forced back into range. Defaults from the CC0 samples and
    the reference set (2026-10-18): medians span -2.5 to +2.3 EV, and only the two dark
    scenes the camera brightened more than we do fall below -2.
    """

    min_median_ev: float = Field(
        default=-2.0,
        ge=-10.0,
        le=10.0,
        description="Darkest median brightness that isn't an outlier, in EV from mid grey.",
    )
    max_median_ev: float = Field(
        default=3.0,
        ge=-10.0,
        le=10.0,
        description="Brightest median brightness that isn't an outlier, in EV from mid grey.",
    )
    max_clipped: float = Field(
        default=0.02,
        ge=0.0,
        le=1.0,
        description="Largest fraction of pixels clipped by the sensor that isn't an outlier.",
    )

    @model_validator(mode="after")
    def _median_range(self) -> "OutliersConfig":
        if self.max_median_ev <= self.min_median_ev:
            raise ValueError("max_median_ev must be greater than min_median_ev")
        return self


class NormaliseConfig(_Model):
    """Stage 2 settings: per-photo exposure, noise reduction, and the checks that flag photos."""

    enabled: bool = Field(default=True, description="Run the normalise stage.")
    exposure: ExposureConfig = Field(default_factory=ExposureConfig)
    chroma_nr: ChromaNoiseReductionConfig = Field(default_factory=ChromaNoiseReductionConfig)
    white_balance: WhiteBalanceConfig = Field(default_factory=WhiteBalanceConfig)
    outliers: OutliersConfig = Field(default_factory=OutliersConfig)


class BlueRenderingConfig(_Model):
    """Render blues (skies) the way camera JPEGs do: deeper, more colourful, a little cyan.

    A camera-matching adjustment in the display transform (ADR-0012), not a creative look.
    Measured against the DJI Pocket 4's and DJI drone's JPEGs, an accurate render of a blue
    sky is paler, lighter and ~4 degrees more purple than the camera's; the defaults are fitted
    to those JPEGs (and checked on held-out photos). Other makers differ (Fujifilm's skies
    are close to accurate), so this is the one place the neutral render leans toward DJI's
    look. Set ``enabled: false`` for a colorimetric sky.

    Applied in display-referred Oklab: a pixel's weight is a raised-cosine window in hue
    around ``hue`` (zero beyond ``hue_width``) times a ramp in chroma from ``chroma_start``
    to ``chroma_full``, so greys, whites and other hues are untouched.
    """

    enabled: bool = Field(
        default=True,
        description=(
            "Apply the camera-matched blue rendering; false leaves blues as the colour "
            "matrix and display transform give them (colorimetric)."
        ),
    )
    hue: float = Field(
        default=250.0,
        ge=0.0,
        lt=360.0,
        description="Centre of the affected hues (Oklab hue, degrees).",
    )
    hue_width: float = Field(
        default=70.0,
        gt=0.0,
        le=120.0,
        description="Hues this far (degrees) or further from the centre are untouched.",
    )
    hue_shift: float = Field(
        default=-4.0,
        ge=-30.0,
        le=30.0,
        description="Hue rotation at the window's centre (degrees); negative turns blue to cyan.",
    )
    chroma: float = Field(
        default=1.3,
        ge=0.5,
        le=2.0,
        description="Chroma (colourfulness) scale at the centre; 1 is none.",
    )
    lightness: float = Field(
        default=0.94, ge=0.5, le=1.5, description="Lightness scale at the centre; below 1 darkens."
    )
    chroma_start: float = Field(
        default=0.01,
        ge=0.0,
        le=0.2,
        description="Oklab chroma below which pixels are untouched (greys and whites).",
    )
    chroma_full: float = Field(
        default=0.05,
        gt=0.0,
        le=0.4,
        description="Oklab chroma at and above which the full adjustment applies.",
    )

    @model_validator(mode="after")
    def _ramp_rises(self) -> "BlueRenderingConfig":
        if self.chroma_full <= self.chroma_start:
            raise ValueError("chroma_full must be greater than chroma_start")
        return self


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
        default=1.15, ge=0.0, le=3.0, description="Overall chroma scale after the curve; 1 is none."
    )
    saturation_fade: float = Field(
        default=0.7,
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
    blue_rendering: BlueRenderingConfig = Field(default_factory=BlueRenderingConfig)

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


class LocalContrastConfig(_Model):
    """Keep detail where the display transform's curve flattens it (ADR-0011).

    Defaults fitted to camera JPEGs: detail keeps at least ``detail_floor`` display stops per
    scene stop, and gets ``amount`` more contrast everywhere.
    """

    enabled: bool = Field(default=True, description="Run local contrast.")
    detail_floor: float = Field(
        default=0.8,
        ge=0.0,
        le=2.0,
        description=(
            "Least contrast detail above mid grey keeps after the display transform, in display "
            "stops per scene stop (the curve's shoulder alone gives ~0.2 in a bright sky)."
        ),
    )
    amount: float = Field(
        default=1.15,
        ge=0.0,
        le=3.0,
        description="Extra detail contrast everywhere; 1 adds none.",
    )
    radius: float = Field(
        default=0.05,
        gt=0.0,
        le=0.25,
        description=(
            "Size of the broad areas whose brightness the curve sets, as a fraction of the "
            "long edge; smaller detail than this counts as detail."
        ),
    )
    edge_ev: float = Field(
        default=1.0,
        gt=0.0,
        le=6.0,
        description=(
            "Steps in brightness much larger than this (in EV), like a horizon, are kept as "
            "edges and not amplified (no halos); smaller ones count as detail."
        ),
    )
    detail_limit_ev: float = Field(
        default=0.25,
        gt=0.0,
        le=3.0,
        description=(
            "Detail larger than about this many EV (a sun glint, a lamp) is amplified less: "
            "what gets added levels off at (gain - 1) times this."
        ),
    )
    max_gain: float = Field(
        default=4.0, ge=1.0, le=10.0, description="Most detail is ever amplified, as a factor."
    )


class GradeConfig(_Model):
    """Stage 3 settings. v0: local contrast and the display transform; looks come in M3."""

    local_contrast: LocalContrastConfig = Field(default_factory=LocalContrastConfig)
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


class NormaliseOverrides(_Model):
    """One photo's normalise overrides; an unset value keeps the project's or computed one.

    ``wb_kelvin`` and ``tint`` re-balance the photo from its as-shot white to the white they
    describe (scene-linear, before exposure). Either alone keeps the as-shot value of the
    other.
    """

    enabled: bool | None = Field(
        default=None,
        description=(
            "Run the normalise stage for this photo; replaces normalise.enabled. false skips "
            "it (exposure, white balance and colour noise reduction)."
        ),
    )
    wb_kelvin: float | None = Field(
        default=None,
        ge=1667.0,
        le=25000.0,
        description=(
            "Colour temperature of the light, in kelvin: the photo is re-balanced from its "
            "as-shot white to this one. Without tint, keeps the as-shot tint."
        ),
    )
    tint: float | None = Field(
        default=None,
        ge=-150.0,
        le=150.0,
        description=(
            "Tint of the light, -1000 x Duv: positive is magenta, negative green. Without "
            "wb_kelvin, keeps the as-shot colour temperature."
        ),
    )
    exposure_ev: float | None = Field(
        default=None,
        ge=-6.0,
        le=10.0,
        description=(
            "Exposure change for this photo, in EV; replaces the computed one (offset_ev plus "
            "any correction)."
        ),
    )


class PhotoOverrides(_Model):
    """Overrides for one photo, keyed in ``photos:`` by the original's file name."""

    normalise: NormaliseOverrides = Field(default_factory=NormaliseOverrides)

    @property
    def sets_white_balance(self) -> bool:
        """Whether a white balance override is set: rendering then needs the as-shot white."""
        return self.normalise.wb_kelvin is not None or self.normalise.tint is not None


NO_OVERRIDES: Final = PhotoOverrides()


class ProjectConfig(_Model):
    """Everything in ``picturesq.yaml``. All sections have defaults, so ``{}`` is valid."""

    version: Literal[1] = Field(default=1, description="Config format version.")
    decode: DecodeConfig = Field(default_factory=DecodeConfig)
    normalise: NormaliseConfig = Field(default_factory=NormaliseConfig)
    grade: GradeConfig = Field(default_factory=GradeConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)
    photos: dict[str, PhotoOverrides] = Field(
        default_factory=dict,
        description=(
            "Per-photo overrides, keyed by the original's file name (matched ignoring case). "
            "Written by the UI or an agent."
        ),
    )

    @model_validator(mode="after")
    def _photo_names_unique(self) -> "ProjectConfig":
        folded = [name.casefold() for name in self.photos]
        if len(set(folded)) != len(folded):
            raise ValueError(
                "photos lists the same file name twice (names are matched ignoring case)"
            )
        return self

    def photo(self, name: str) -> PhotoOverrides:
        """The overrides of the original named ``name`` (ignoring case); empty if it has none.

        Case is ignored as on Windows and macOS, where ``IMG.DNG`` and ``img.dng`` are one file.
        """
        overrides = self.photos.get(name)
        if overrides is not None:
            return overrides
        folded = name.casefold()
        for key, value in self.photos.items():
            if key.casefold() == folded:
                return value
        return NO_OVERRIDES
