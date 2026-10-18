"""Flags: normalise saying "look at this photo", without changing it.

A flag never alters the pixels (plan principle: outliers are flagged, not forced). Each has a
``name`` from a fixed set (the glossary lists them), a one-line ``message`` for people and
``details`` for agents and the UI.

- ``exposure_clamped``: exposure correction wanted more than ``max_correction_ev``.
- ``outlier``: one of the photo's stats is outside its range in ``normalise.outliers``; one
  flag per stat.
"""

from dataclasses import dataclass, field
from typing import Final

from picturesq.config import ExposureConfig, OutliersConfig
from picturesq.normalise.exposure import ExposureDecision
from picturesq.normalise.stats import PhotoStats

EXPOSURE_CLAMPED: Final = "exposure_clamped"
OUTLIER: Final = "outlier"

Detail = float | str


@dataclass(frozen=True)
class Flag:
    """One reason to look at a photo."""

    name: str
    message: str
    details: dict[str, Detail] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """JSON-ready."""
        return {"flag": self.name, "message": self.message, "details": dict(self.details)}


def exposure_flags(decision: ExposureDecision, config: ExposureConfig) -> list[Flag]:
    """``exposure_clamped`` if the correction hit its limit."""
    if not decision.clamped:
        return []
    return [
        Flag(
            EXPOSURE_CLAMPED,
            f"exposure correction limited to {decision.correction_ev:+.2f} EV "
            f"(max_correction_ev {config.max_correction_ev:g})",
            {
                "correction_ev": round(decision.correction_ev, 3),
                "limit_ev": config.max_correction_ev,
            },
        )
    ]


def outlier_flags(stats: PhotoStats, config: OutliersConfig) -> list[Flag]:
    """One ``outlier`` flag per stat outside its range (range ends are inside)."""
    flags: list[Flag] = []
    median = stats.p50_ev
    if median < config.min_median_ev:
        flags.append(
            _outlier(
                "p50_ev",
                median,
                f"median {median:+.2f} EV is darker than {config.min_median_ev:+.2f} EV",
                minimum=config.min_median_ev,
            )
        )
    if median > config.max_median_ev:
        flags.append(
            _outlier(
                "p50_ev",
                median,
                f"median {median:+.2f} EV is brighter than {config.max_median_ev:+.2f} EV",
                maximum=config.max_median_ev,
            )
        )
    if stats.clipped > config.max_clipped:
        flags.append(
            _outlier(
                "clipped",
                stats.clipped,
                f"{stats.clipped:.1%} of pixels clipped (more than {config.max_clipped:.1%})",
                maximum=config.max_clipped,
            )
        )
    return flags


def _outlier(
    stat: str,
    value: float,
    message: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> Flag:
    details: dict[str, Detail] = {"stat": stat, "value": round(value, 5)}
    if minimum is not None:
        details["min"] = minimum
    if maximum is not None:
        details["max"] = maximum
    return Flag(OUTLIER, message, details)
