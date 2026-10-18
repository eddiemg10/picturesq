"""Flags: normalise saying "look at this photo", without changing it.

A flag never alters the pixels (plan principle: outliers are flagged, not forced). Each has a
``name`` from a fixed set (the glossary lists them), a one-line ``message`` for people and
``details`` for agents and the UI.

- ``exposure_clamped``: exposure correction wanted more than ``max_correction_ev``.
- ``wb_disagreement``: both white balance estimates differ from the as-shot white by at
  least ``flag_disagreement_mired``, the same way (:mod:`.white_balance_check`).
- ``outlier``: one of the photo's stats is outside its range in ``normalise.outliers``; one
  flag per stat.
"""

from dataclasses import dataclass, field
from typing import Final

from picturesq.config import ExposureConfig, OutliersConfig, WhiteBalanceConfig
from picturesq.normalise.exposure import ExposureDecision
from picturesq.normalise.stats import PhotoStats
from picturesq.normalise.white_balance_check import WhiteBalanceCheck

EXPOSURE_CLAMPED: Final = "exposure_clamped"
OUTLIER: Final = "outlier"
WB_DISAGREEMENT: Final = "wb_disagreement"

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


def white_balance_flags(check: WhiteBalanceCheck, config: WhiteBalanceConfig) -> list[Flag]:
    """``wb_disagreement`` if the white balance check disagrees with the as-shot white."""
    brightest, grey = check.brightest, check.grey
    if not check.disagrees or brightest is None or grey is None or check.as_shot_kelvin is None:
        return []
    warmer = brightest.delta_mired > 0.0
    low, high = sorted((abs(brightest.delta_mired), abs(grey.delta_mired)))
    return [
        Flag(
            WB_DISAGREEMENT,
            f"the light looks {low:.0f} to {high:.0f} mired {'warmer' if warmer else 'cooler'} "
            f"than the as-shot white balance ({check.as_shot_kelvin:.0f} K); the photo may "
            f"look too {'warm' if warmer else 'cool'}",
            {
                "as_shot_kelvin": round(check.as_shot_kelvin, 1),
                "as_shot_tint": round(check.as_shot_tint or 0.0, 1),
                "brightest_kelvin": round(brightest.kelvin, 1),
                "brightest_delta_mired": round(brightest.delta_mired, 1),
                "grey_kelvin": round(grey.kelvin, 1),
                "grey_delta_mired": round(grey.delta_mired, 1),
                "limit_mired": config.flag_disagreement_mired,
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
