"""How normalise sees a project: per photo, on its proxy, the white balance check, exposure,
stats and flags; written to ``<project>/.picturesq/stats/``.

Behind ``picturesq normalise`` (and later the UI's review panel). Per photo:

1. **White balance check** on the decoded proxy, *before* normalise: it checks the camera's
   as-shot white, which a ``wb_kelvin`` / ``tint`` override would hide.
2. **Normalise** with the photo's overrides (:func:`~picturesq.normalise.normalise_with_decision`),
   which says how the exposure was chosen.
3. **Stats** of the normalised proxy. The clip level is the photo info's, times
   ``2**exposure_ev``: exposure scales the clipped values with everything else, the same
   way :func:`~picturesq.normalise.check_white_balance` treats an exposed image. (A white
   balance override scales the channels unequally, so its clip test is approximate.)
4. **Flags**: ``exposure_clamped`` (not with an ``exposure_ev`` override, which replaces
   the correction), ``wb_disagreement`` (not with a ``wb_kelvin`` / ``tint`` override: the
   photo's white balance has been chosen by hand), and ``outlier``.

With ``enabled: false`` (project or override) the photo isn't normalised: its stats are
those of the decoded proxy (clip level unscaled) and it has no exposure flag.

A photo that fails (its original can't be decoded, an impossible override) is recorded with
its error and the run carries on, as in export.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from picturesq import __version__
from picturesq.atomic import atomic_write
from picturesq.colour.transfer import FloatArray
from picturesq.config import ProjectConfig
from picturesq.decode import DecodeError, PhotoInfo, read_photo_info
from picturesq.normalise import (
    ExposureDecision,
    Flag,
    PhotoStats,
    WhiteBalanceCheck,
    WhiteBalanceOverrideError,
    check_white_balance,
    exposure_flags,
    normalise_with_decision,
    outlier_flags,
    photo_stats,
    white_balance_flags,
)
from picturesq.photo import PhotoContext
from picturesq.pipeline.proxy import load_proxy

STATS_DIRNAME: Final = "stats"
SUMMARY_FILENAME: Final = "summary.json"
_EV_DECIMALS: Final = 3


def _ev(value: float) -> float:
    return round(value, _EV_DECIMALS)


@dataclass
class NormaliseResult:
    """How normalise sees one photo. Everything but ``name`` is None/empty if it failed."""

    name: str
    proxy_key: str | None = None
    """The proxy's cache key: stats with another key are stale."""
    info: PhotoInfo | None = None
    exposure: ExposureDecision | None = None
    """How the exposure was chosen; None when the photo isn't normalised (or failed)."""
    overrides: dict[str, Any] = field(default_factory=dict)
    """The photo's normalise overrides that are set (``photos.<name>.normalise``)."""
    stats: PhotoStats | None = None
    white_balance: WhiteBalanceCheck | None = None
    flags: list[Flag] = field(default_factory=list)
    error: str | None = None

    @property
    def normalised(self) -> bool:
        return self.exposure is not None

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready; the contents of ``stats/<stem>.json`` (plus ``version`` there)."""
        exposure = self.exposure
        return {
            "photo": self.name,
            "proxy_key": self.proxy_key,
            "normalised": self.normalised,
            "exposure_ev": None if exposure is None else _ev(exposure.ev),
            "correction_ev": None if exposure is None else _ev(exposure.correction_ev),
            "overrides": dict(self.overrides),
            "info": None if self.info is None else self.info.to_dict(),
            "stats": None if self.stats is None else self.stats.to_dict(),
            "white_balance": None if self.white_balance is None else self.white_balance.to_dict(),
            "flags": [flag.to_dict() for flag in self.flags],
            "error": self.error,
        }


def normalise_proxy(
    image: FloatArray, name: str, info: PhotoInfo, config: ProjectConfig
) -> NormaliseResult:
    """Check, normalise (in place), measure and flag one photo's proxy ``image``.

    ``name`` is the original's file name (it keys the overrides); ``info`` its photo info.
    Pure, no IO. Raises WhiteBalanceOverrideError like :func:`~picturesq.normalise.normalise`.
    """
    settings = config.normalise
    overrides = config.photo(name).normalise
    white_balance = check_white_balance(image, info, settings.white_balance)
    decision = normalise_with_decision(image, config, PhotoContext(name=name, info=info))
    applied_ev = 0.0 if decision is None else decision.ev
    stats = photo_stats(image, info.clip_level * 2.0**applied_ev)
    flags: list[Flag] = []
    if decision is not None and overrides.exposure_ev is None:
        flags += exposure_flags(decision, settings.exposure)
    if overrides.wb_kelvin is None and overrides.tint is None:
        flags += white_balance_flags(white_balance, settings.white_balance)
    flags += outlier_flags(stats, settings.outliers)
    return NormaliseResult(
        name=name,
        info=info,
        exposure=decision,
        overrides=overrides.model_dump(exclude_none=True),
        stats=stats,
        white_balance=white_balance,
        flags=flags,
    )


def normalise_originals(
    originals: Sequence[Path],
    config: ProjectConfig,
    cache_dir: Path,
    *,
    on_photo: Callable[[NormaliseResult], None] | None = None,
) -> list[NormaliseResult]:
    """:func:`normalise_proxy` for each original, on its proxy (built if missing).

    One proxy in memory at a time. A photo that fails is recorded and the run continues.
    """
    results: list[NormaliseResult] = []
    for original in originals:
        result = NormaliseResult(name=original.name)
        try:
            if original.stem.casefold() == Path(SUMMARY_FILENAME).stem:
                raise ValueError(
                    f"{original.name}: a photo named 'summary' would overwrite the project "
                    f"summary in {STATS_DIRNAME}/{SUMMARY_FILENAME}; rename it"
                )
            proxy = load_proxy(original, config.decode, cache_dir)
            info = read_photo_info(original, config.decode)
            result = normalise_proxy(proxy.image, original.name, info, config)
            result.proxy_key = proxy.key
            del proxy
        except (DecodeError, OSError, ValueError, WhiteBalanceOverrideError) as error:
            result.error = str(error)
        results.append(result)
        if on_photo is not None:
            on_photo(result)
    return results


def unmatched_overrides(config: ProjectConfig, originals: Sequence[Path]) -> list[str]:
    """Names in ``photos:`` that match no original (ignoring case): likely typos."""
    names = {original.name.casefold() for original in originals}
    return sorted(name for name in config.photos if name.casefold() not in names)


def summarise(results: Sequence[NormaliseResult], unmatched: Sequence[str] = ()) -> dict[str, Any]:
    """The project summary: counts, flagged and failed photos, and the spread of medians.

    ``median_ev`` describes the photos' median brightness after normalise (``p50_ev``):
    the median of the medians, the darkest and brightest, and ``spread`` (brightest minus
    darkest), which is how even the batch is. None if no photo has stats.
    """
    measured = [r for r in results if r.stats is not None]
    medians = [r.stats.p50_ev for r in measured if r.stats is not None]
    flag_counts: dict[str, int] = {}
    for result in results:
        for flag in result.flags:
            flag_counts[flag.name] = flag_counts.get(flag.name, 0) + 1
    median_ev = None
    if medians:
        median_ev = {
            "median": _ev(statistics.median(medians)),
            "min": _ev(min(medians)),
            "max": _ev(max(medians)),
            "spread": _ev(max(medians) - min(medians)),
        }
    return {
        "photos": len(results),
        "failed": sum(1 for r in results if r.error is not None),
        "flagged": sum(1 for r in results if r.flags),
        "flags": dict(sorted(flag_counts.items())),
        "flagged_photos": [r.name for r in results if r.flags],
        "failed_photos": [r.name for r in results if r.error is not None],
        "median_ev": median_ev,
        "unmatched_overrides": list(unmatched),
    }


def _json_bytes(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_stats(
    results: Sequence[NormaliseResult], summary: dict[str, Any], cache_dir: Path
) -> Path:
    """Write ``stats/<stem>.json`` per photo and ``stats/summary.json``; returns the folder.

    Atomic, sorted keys, no timestamps or absolute paths: the same project gives the same
    bytes. Each file carries the picturesq version (and each photo its proxy key) so stale
    stats can be told apart. Stats of photos no longer in the project are removed.
    """
    folder = cache_dir / STATS_DIRNAME
    written: set[str] = {SUMMARY_FILENAME}
    for result in results:
        filename = f"{Path(result.name).stem}.json"
        if filename.casefold() == SUMMARY_FILENAME:
            continue  # refused in normalise_originals; never overwrite the summary
        atomic_write(folder / filename, _json_bytes({"version": __version__, **result.to_dict()}))
        written.add(filename)
    atomic_write(folder / SUMMARY_FILENAME, _json_bytes({"version": __version__, **summary}))
    for stale in folder.glob("*.json"):
        if stale.name not in written:
            stale.unlink(missing_ok=True)
    return folder
