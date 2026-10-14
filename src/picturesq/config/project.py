"""Project config model: the contents of ``<project>/picturesq.yaml``.

v0 holds the decode and export sections (M1). Normalise, grade and per-photo overrides
are added in the milestones that implement them, so the config never offers a setting
the pipeline ignores.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

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


class OutputConfig(_Model):
    """One export target, e.g. ``web`` or ``archive``."""

    long_edge: int | None = Field(
        default=None, gt=0, description="Long edge in pixels; null keeps the full resolution."
    )
    quality: int = Field(default=90, ge=1, le=100, description="JPEG quality.")


def _default_outputs() -> dict[str, OutputConfig]:
    return {
        "web": OutputConfig(long_edge=2048, quality=90),
        "archive": OutputConfig(long_edge=None, quality=95),
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
    export: ExportConfig = Field(default_factory=ExportConfig)
