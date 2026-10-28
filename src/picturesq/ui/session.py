"""One project open in the UI: its config on disk, its photos, and previews rendered on demand.

The session is the only thing the web app talks to. It owns:

- **The config.** Read from ``picturesq.yaml`` and reloaded when its modification time
  changes (an agent edited it); every edit from the UI is validated by the config models and
  written atomically (ADR-0004). ``revision`` increases on every change, from either side, so
  the browser knows when its previews are stale.
- **Normalised bases.** Each photo's proxy is loaded once (its cache key needs the original's
  hash, which is slow on network drives, so it is computed once per original size and
  modification time), normalised with the photo's overrides, and reduced to the two sizes
  the UI shows: ``thumb`` and ``large``. Kept in memory (thumbs for every photo, larges for
  the most recent few), keyed by everything normalise reads, so an override change
  re-normalises only that photo.
- **Capture times.** Each original's camera time, read once (EXIF only), and the
  corrected time its exports carry under ``metadata`` (``picturesq.metadata``, as the CLI).
- **Previews.** A base through a look and adjustments, the display transform and sRGB, as a
  JPEG; the same functions an export uses (``grade_with``, ``render_output``), so what the
  UI shows is what export writes, at a smaller size.

Renders are serialised by one lock: they already use every core (``picturesq.parallel``), and
one at a time bounds memory.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import threading
from collections import OrderedDict
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Literal

import numpy as np
from PIL import Image
from pydantic import ValidationError

from picturesq.atomic import atomic_write
from picturesq.colour.transfer import FloatArray
from picturesq.config import (
    CONFIG_FILENAME,
    AdjustmentsConfig,
    ConfigError,
    LookChoice,
    LookFileError,
    LookParameterError,
    OutputConfig,
    ProjectConfig,
    SharpenConfig,
    dump_project_config,
    load_project_config,
)
from picturesq.config import look as look_files
from picturesq.config.look import Look
from picturesq.config.time_shift import format_time_shift, parse_compact_shift
from picturesq.decode import (
    DecodeError,
    PhotoInfo,
    find_originals,
    read_capture_exif,
    read_photo_info,
)
from picturesq.export import resize_to_long_edge, sha256_file
from picturesq.grade import grade_with
from picturesq.metadata import (
    CaptureTimeError,
    camera_capture_time,
    parse_clock_time,
    photo_capture_time,
    shift_from_reference,
)
from picturesq.normalise import WhiteBalanceOverrideError
from picturesq.photo import PhotoContext, ResolvedLook
from picturesq.pipeline.export import EXPORTS_DIRNAME, render_output
from picturesq.pipeline.looks import resolve_choice
from picturesq.pipeline.metadata import rewrite_exports
from picturesq.pipeline.normalise import NormaliseResult, normalise_proxy
from picturesq.pipeline.proxy import CACHE_DIRNAME, load_proxy, proxy_key, proxy_path

Size = Literal["thumb", "medium", "large"]
LONG_EDGES: Final[dict[Size, int]] = {"thumb": 480, "medium": 960, "large": 1600}
"""Long edge of each base, in pixels. ``large`` fills a laptop screen's preview area;
``medium`` is what a moving slider renders (about 3x faster), replaced by ``large`` when it
stops."""
HASHES_FILENAME: Final = "originals.json"
"""``<project>/.picturesq/originals.json``: each original's SHA-256 by size and modification
time, so reopening a project doesn't re-read every original (slow on network and Windows
drives seen from WSL)."""
PREVIEW_SHARPEN: Final = SharpenConfig(amount=0.3, radius=0.7)
"""Light sharpening for on-screen previews (exports use their output's own)."""
JPEG_QUALITY: Final = 88
LARGE_BASES_KEPT: Final = 6
"""Large bases kept in memory (~33 MB each at 1600 px, 16:9)."""
PREVIEWS_KEPT: Final = 600
"""Encoded preview JPEGs kept in memory (~30-200 KB each)."""


class EditError(ValueError):
    """An edit the config models reject; the message is user-facing."""


@dataclass
class _Original:
    path: Path
    signature: tuple[int, int]
    """(size, modification time in ns): when it changes, the original's hash is recomputed."""
    key: str | None = None
    info: PhotoInfo | None = None
    camera_time: datetime | None = None
    camera_time_read: bool = False


@dataclass
class PhotoState:
    """What the UI shows about one photo besides its pixels."""

    name: str
    normalise: NormaliseResult | None = None
    error: str | None = None


@dataclass
class Variant:
    """What to render a photo with: a look (None: none) and adjustments."""

    look: ResolvedLook | None
    adjustments: AdjustmentsConfig
    neutral: bool = False

    def key(self) -> str:
        look = None
        if self.look is not None:
            chosen = self.look
            look = [chosen.key, chosen.sha256, chosen.intensity, dict(chosen.parameters)]
        return json.dumps([look, self.adjustments.model_dump(), self.neutral], sort_keys=True)


@dataclass
class _Base:
    """A photo's normalised proxy, reduced to one size."""

    key: str
    image: FloatArray


class _PriorityLock:
    """A lock that waiting urgent holders get before waiting ordinary ones."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._held = False
        self._urgent_waiting = 0

    @contextlib.contextmanager
    def hold(self, *, urgent: bool) -> Iterator[None]:
        with self._condition:
            if urgent:
                self._urgent_waiting += 1
            try:
                while self._held or (not urgent and self._urgent_waiting):
                    self._condition.wait()
            finally:
                if urgent:
                    self._urgent_waiting -= 1
            self._held = True
        try:
            yield
        finally:
            with self._condition:
                self._held = False
                self._condition.notify_all()


@dataclass
class Session:
    """A project open in the UI. Thread-safe: the web server calls it from worker threads."""

    project: Path
    config: ProjectConfig = field(default_factory=ProjectConfig)
    library: dict[str, Look] = field(default_factory=dict)
    revision: int = 0
    analysed: int = 0
    """Increases whenever a photo is normalised (or fails to be): its flags, measured
    exposure and errors in :meth:`state` may have changed, though no preview has."""
    _mtime: int | None = None
    _originals: dict[str, _Original] = field(default_factory=dict)
    _photos: dict[str, PhotoState] = field(default_factory=dict)
    _thumbs: dict[str, _Base] = field(default_factory=dict)
    _mediums: OrderedDict[str, _Base] = field(default_factory=OrderedDict)
    _larges: OrderedDict[str, _Base] = field(default_factory=OrderedDict)
    _previews: OrderedDict[str, bytes] = field(default_factory=OrderedDict)
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _renders: _PriorityLock = field(default_factory=lambda: _PriorityLock())

    @classmethod
    def open(cls, project: Path) -> Session:
        """Open ``project``: read its config (defaults if it has none, not written until the
        first edit), list its originals and load the look library.

        Raises ConfigError for an invalid config, LookFileError for a broken look library.
        """
        session = cls(project=project, library=look_files.look_library())
        session.reload(force=True)
        return session

    # --- config -------------------------------------------------------------------------

    @property
    def config_path(self) -> Path:
        return self.project / CONFIG_FILENAME

    @property
    def cache_dir(self) -> Path:
        return self.project / CACHE_DIRNAME

    def _config_mtime(self) -> int | None:
        try:
            return self.config_path.stat().st_mtime_ns
        except FileNotFoundError:
            return None

    def reload(self, *, force: bool = False) -> bool:
        """Re-read the config and the list of originals if the config file changed since it
        was last read or written. Returns whether anything was reloaded.

        An invalid config on disk (a bad agent edit) is reported by raising ConfigError and
        the session keeps the last valid one.
        """
        with self._lock:
            mtime = self._config_mtime()
            if not force and mtime == self._mtime:
                return False
            self._mtime = mtime
            config = ProjectConfig() if mtime is None else load_project_config(self.config_path)
            self.config = config
            self._refresh_originals()
            self.revision += 1
            return True

    def _refresh_originals(self) -> None:
        found = {path.name: path for path in find_originals(self.project)}
        for name in list(self._originals):
            if name not in found:
                del self._originals[name]
        for name, path in found.items():
            stat = path.stat()
            signature = (stat.st_size, stat.st_mtime_ns)
            known = self._originals.get(name)
            if known is None or known.signature != signature:
                self._originals[name] = _Original(path=path, signature=signature)
        self._photos = {name: self._photos.get(name, PhotoState(name)) for name in found}

    def _save(self, config: ProjectConfig) -> None:
        atomic_write(self.config_path, dump_project_config(config).encode("utf-8"))
        self.config = config
        self._mtime = self._config_mtime()
        self.revision += 1

    def edit(self, change: Mapping[str, Any]) -> ProjectConfig:
        """Apply one edit from the UI and save it. Returns the new config.

        ``change`` has a ``target``: ``"project"`` or a list of photo names. Then any of:

        - ``look``: a look choice (``{"name", "intensity", "parameters"}``), or None. For the
          project, None means no look. For photos, None removes the override (the photo
          follows the project's look); ``{"name": None}`` grades it with no look.
        - ``adjustments``: a partial mapping of adjustment values. For photos, a None value
          removes that override.
        - ``normalise``: (photos only) a partial mapping of normalise overrides
          (``exposure_ev``, ``wb_kelvin``, ``tint``, ``enabled``); None removes one.
        - ``reset``: (photos only) true removes all of the photos' overrides first (not
          their capture times: those aren't a grade).
        - ``metadata``: for the project, any of ``time_shift`` (``+1h``, ``-1d2h30m`` or
          ``+9598d 10:05:00``; None removes it), ``time_zone`` (``+01:00``; None removes it)
          and ``reference`` (``{"photo", "actual"}``: set the shift so that photo's camera
          time becomes ``actual``, as ``picturesq metadata shift --photo --actual``). For
          photos, ``capture_time`` (``2026-10-17 20:05``; None removes it).

        Raises EditError (nothing is saved) if the result isn't a valid config or a look
        doesn't resolve.
        """
        with self._lock:
            self.reload()
            data = self.config.model_dump(mode="json", exclude_unset=False)
            target = change.get("target")
            if target == "project":
                grade = data["grade"]
                if "look" in change:
                    grade["look"] = _look_value(change["look"])
                for key, value in (change.get("adjustments") or {}).items():
                    grade["adjustments"][key] = 0.0 if value is None else value
                if change.get("metadata"):
                    data["metadata"].update(self._project_metadata(change["metadata"]))
            elif isinstance(target, list) and target:
                photos = data.setdefault("photos", {})
                for name in target:
                    if name not in self._originals:
                        raise EditError(f"no photo named {name!r} in this project")
                    entry = _photo_entry(photos, name)
                    if change.get("reset"):
                        # Metadata (the capture time) is not a grade: reset keeps it.
                        for key in [key for key in entry if key != "metadata"]:
                            del entry[key]
                    grade = entry.setdefault("grade", {})
                    if "look" in change:
                        project_look = self.config.grade.look
                        value = _look_value(
                            change["look"],
                            project_look=None if project_look is None else project_look.name,
                        )
                        if value is None:
                            grade.pop("look", None)
                        else:
                            grade["look"] = value
                    _merge(grade.setdefault("adjustments", {}), change.get("adjustments"))
                    _merge(entry.setdefault("normalise", {}), change.get("normalise"))
                    _merge(entry.setdefault("metadata", {}), _photo_metadata(change))
                    _prune(photos, name)
            else:
                raise EditError("target must be 'project' or a list of photo names")
            try:
                config = ProjectConfig.model_validate(data)
                for name in [None, *config.photos]:
                    choice = config.photo_look(name or "")
                    if choice is not None:
                        resolve_choice(choice, self.library)
            except ValidationError as error:
                raise EditError(_validation_message(error)) from None
            except (LookFileError, LookParameterError) as error:
                raise EditError(str(error)) from None
            self._save(config)
            return self.config

    def _project_metadata(self, change: Mapping[str, Any]) -> dict[str, Any]:
        """A project ``metadata`` edit as config data. Raises EditError."""
        values: dict[str, Any] = {}
        try:
            if "time_shift" in change:
                shift = change["time_shift"] or "+0s"
                values["time_shift"] = format_time_shift(parse_compact_shift(shift))
            if "time_zone" in change:
                values["time_zone"] = change["time_zone"] or None
            reference = change.get("reference")
            if reference:
                name = reference.get("photo")
                if name not in self._originals:
                    raise EditError(f"no photo named {name!r} in this project")
                camera = self._camera_time(self._originals[name])
                if camera is None:
                    raise EditError(f"{name} records no capture time to compare with")
                actual = parse_clock_time(str(reference.get("actual", "")))
                values["time_shift"] = format_time_shift(shift_from_reference(camera, actual))
        except ValueError as error:
            raise EditError(str(error)) from None
        return values

    # --- photos -------------------------------------------------------------------------

    @property
    def names(self) -> list[str]:
        return list(self._photos)

    def photo_state(self, name: str) -> PhotoState:
        return self._photos[name]

    def _original(self, name: str) -> _Original:
        try:
            return self._originals[name]
        except KeyError:
            raise KeyError(f"no photo named {name!r}") from None

    def _proxy_key(self, original: _Original) -> str:
        if original.key is None:
            original.key = proxy_key(self._sha256(original), self.config.decode)
        return original.key

    def _sha256(self, original: _Original) -> str:
        path = self.cache_dir / HASHES_FILENAME
        with self._lock:
            try:
                known = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                known = {}
            entry = known.get(original.path.name)
            if isinstance(entry, dict) and entry.get("signature") == list(original.signature):
                return str(entry["sha256"])
        digest = sha256_file(original.path)
        with self._lock:
            known[original.path.name] = {"signature": list(original.signature), "sha256": digest}
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write(path, json.dumps(known, indent=1, sort_keys=True).encode("utf-8"))
            except OSError:
                pass  # only a cache: the next open hashes again
        return digest

    def _info(self, original: _Original) -> PhotoInfo:
        if original.info is None:
            original.info = read_photo_info(original.path, self.config.decode)
        return original.info

    def _camera_time(self, original: _Original) -> datetime | None:
        if not original.camera_time_read:
            original.camera_time = camera_capture_time(read_capture_exif(original.path))
            original.camera_time_read = True
        return original.camera_time

    def _capture(self, name: str, config: ProjectConfig) -> dict[str, Any]:
        """Photo ``name``'s camera time and the corrected time its exports carry, JSON-ready."""
        camera = self._camera_time(self._originals[name])
        try:
            when = photo_capture_time(config, name, camera)
        except CaptureTimeError as error:
            return {"camera": _iso(camera), "corrected": None, "how": str(error), "own": False}
        return {
            "camera": _iso(when.camera),
            "corrected": _iso(when.corrected),
            "how": when.how,
            "own": when.overridden,
        }

    def rewrite_export_dates(self, outputs: list[str]) -> dict[str, Any]:
        """Rewrite the dates in exports already written (``picturesq metadata apply``), for
        ``outputs`` in ``<project>/exports``. Returns counts and failures, JSON-ready."""
        with self._lock:
            config = self.config
            originals = [original.path for original in self._originals.values()]
        results = rewrite_exports(self.project / EXPORTS_DIRNAME, outputs, config, originals)
        return {
            "exports": len(results),
            "rewritten": sum(result.changed for result in results),
            "failed": [f"{r.path.name}: {r.error}" for r in results if r.error is not None],
        }

    def _base_key(self, name: str, config: ProjectConfig) -> str:
        """Everything the normalised base of photo ``name`` depends on."""
        material = {
            "decode": config.decode.model_dump(mode="json"),
            "normalise": config.normalise.model_dump(mode="json"),
            "overrides": config.photo(name).normalise.model_dump(mode="json"),
        }
        return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()[:16]

    def _load_proxy(self, original: _Original) -> FloatArray:
        key = self._proxy_key(original)
        path = proxy_path(self.cache_dir, original.path, key)
        if path.exists():
            try:
                image = np.load(path, allow_pickle=False)
                if image.dtype == np.float16 and image.ndim == 3:
                    return image.astype(np.float32)
            except (OSError, ValueError, EOFError):
                pass
        return load_proxy(original.path, self.config.decode, self.cache_dir).image

    def base(self, name: str, size: Size, *, urgent: bool = True) -> FloatArray:
        """Photo ``name``'s normalised proxy at ``size`` (cached). Raises DecodeError,
        OSError, WhiteBalanceOverrideError or KeyError (unknown photo).

        Reading the proxy happens outside the render lock (it is slow on network drives);
        normalising waits its turn there, ``urgent`` ahead of the others."""
        with self._lock:
            config = self.config
            original = self._original(name)
            key = self._base_key(name, config)
            cached = self._thumbs.get(name) if size == "thumb" else self._larges.get(name)
            if cached is not None and cached.key == key:
                if size == "thumb":
                    return cached.image
                self._larges.move_to_end(name)
                if size == "large":
                    return cached.image
                medium = self._mediums.get(name)
                if medium is not None and medium.key == key:
                    return medium.image
                image = resize_to_long_edge(cached.image, LONG_EDGES["medium"])
                self._mediums[name] = _Base(key, image)
                while len(self._mediums) > LARGE_BASES_KEPT:
                    self._mediums.popitem(last=False)
                return image
        state = self._photos[name]
        try:
            proxy = self._load_proxy(original)
            info = self._info(original)
            with self._renders.hold(urgent=urgent):
                state.normalise = normalise_proxy(proxy, name, info, config)
                thumb = resize_to_long_edge(proxy, LONG_EDGES["thumb"])
                large = resize_to_long_edge(proxy, LONG_EDGES["large"])
            state.error = None
        except (DecodeError, OSError, ValueError, WhiteBalanceOverrideError) as error:
            state.error = str(error)
            raise
        finally:
            with self._lock:
                self.analysed += 1
        large = large.copy() if large is proxy else large
        del proxy
        with self._lock:
            self._thumbs[name] = _Base(key, thumb)
            self._larges[name] = _Base(key, large)
            while len(self._larges) > LARGE_BASES_KEPT:
                self._larges.popitem(last=False)
        if size == "medium":
            return self.base(name, size)
        return thumb if size == "thumb" else large

    def warm(self) -> None:
        """Normalise every photo's thumb base (in order), so the strip fills quickly. Runs in
        a background thread, behind any render; a photo that fails is skipped (its error is
        in its state)."""
        for name in list(self._photos):
            try:
                self.base(name, "thumb", urgent=False)
            except (DecodeError, OSError, ValueError, WhiteBalanceOverrideError, KeyError):
                continue

    # --- previews -----------------------------------------------------------------------

    def variant(
        self,
        name: str,
        which: str,
        draft: Mapping[str, Any] | None = None,
    ) -> Variant:
        """The variant ``which`` of photo ``name``:

        - ``current``: its look and adjustments from config (with ``draft`` applied: an
          unsaved ``{"look": ..., "adjustments": ...}`` while a slider moves);
        - ``neutral``: no look, no adjustments;
        - ``look:<category/name>``: that look (the photo's own intensity and parameters if
          it is the photo's look, else 100 % with its defaults), with the photo's
          adjustments, as in ``picturesq preview``;
        - ``none``: no look, with the photo's adjustments.

        Raises EditError for an unknown look or bad values.
        """
        config = self.config
        choice = config.photo_look(name)
        adjustments = config.photo_adjustments(name)
        try:
            if which == "neutral":
                return Variant(None, AdjustmentsConfig(), neutral=True)
            if which == "none":
                return Variant(None, adjustments)
            if which.startswith("look:"):
                key = which.removeprefix("look:")
                own = choice if choice is not None and choice.name == key else None
                resolved = resolve_choice(own or LookChoice(name=key), self.library)
                return Variant(resolved, adjustments)
            if which != "current":
                raise EditError(f"unknown variant {which!r}")
            if draft:
                if "look" in draft:
                    value = draft["look"]
                    choice = None if not value or not value.get("name") else LookChoice(**value)
                    if choice is not None and choice.intensity == 0.0:
                        choice = None
                if "adjustments" in draft:
                    values = {k: v for k, v in draft["adjustments"].items() if v is not None}
                    adjustments = adjustments.model_copy(
                        update=AdjustmentsConfig(
                            **{**adjustments.model_dump(), **values}
                        ).model_dump()
                    )
            look = None if choice is None else resolve_choice(choice, self.library)
            return Variant(look, adjustments)
        except ValidationError as error:
            raise EditError(_validation_message(error)) from None
        except (LookFileError, LookParameterError) as error:
            raise EditError(str(error)) from None

    def preview(self, name: str, size: Size, variant: Variant) -> bytes:
        """Photo ``name`` at ``size`` through ``variant``, as sRGB JPEG bytes (cached).

        The photo being looked at (``medium`` and ``large``) renders before any waiting
        thumbnails."""
        with self._lock:
            config = self.config
            key = json.dumps(
                [name, size, self._base_key(name, config), variant.key(), _grade_key(config)]
            )
            cached = self._previews.get(key)
            if cached is not None:
                self._previews.move_to_end(key)
                return cached
        urgent = size != "thumb"
        image = self.base(name, size, urgent=urgent).copy()
        with self._renders.hold(urgent=urgent):
            photo = PhotoContext(name=name, look=variant.look)
            grade_with(image, config, photo, variant.adjustments)
            view = OutputConfig(long_edge=None, sharpen=PREVIEW_SHARPEN)
            pixels = render_output(
                image, view, config.grade.display_transform, photo=photo, consume=True
            )
        buffer = io.BytesIO()
        Image.fromarray(pixels).save(buffer, format="JPEG", quality=JPEG_QUALITY)
        data = buffer.getvalue()
        with self._lock:
            self._previews[key] = data
            while len(self._previews) > PREVIEWS_KEPT:
                self._previews.popitem(last=False)
        return data

    # --- state for the browser ----------------------------------------------------------

    def state(self) -> dict[str, Any]:
        """Everything the browser needs to draw the page, JSON-ready."""
        with self._lock:
            config = self.config
            photos = []
            for name, photo_state in self._photos.items():
                overrides = config.photo(name)
                result = photo_state.normalise
                photos.append(
                    {
                        "name": name,
                        "look": _choice_dict(config.photo_look(name)),
                        "look_override": overrides.grade.look is not None,
                        "adjustments": config.photo_adjustments(name).model_dump(),
                        "adjustment_overrides": overrides.grade.adjustments.model_dump(
                            exclude_none=True
                        ),
                        "normalise": overrides.normalise.model_dump(exclude_none=True),
                        "exposure_ev": None
                        if result is None or result.exposure is None
                        else round(result.exposure.ev, 2),
                        "as_shot": None
                        if result is None or result.info is None
                        else _as_shot(result.info),
                        "analysed": result is not None or photo_state.error is not None,
                        "flags": [] if result is None else [f.to_dict() for f in result.flags],
                        "capture": self._capture(name, config),
                        "error": photo_state.error,
                    }
                )
            return {
                "project": self.project.resolve().name,
                "revision": self.revision,
                "analysed": self.analysed,
                "config_exists": self._mtime is not None,
                "look": _choice_dict(config.grade.look),
                "adjustments": config.grade.adjustments.model_dump(),
                "exposure_offset_ev": config.normalise.exposure.offset_ev,
                "metadata": config.metadata.model_dump(),
                "photos": photos,
                "looks": [_look_dict(look) for look in self.library.values()],
                "outputs": {
                    name: config.export.outputs[name].model_dump() for name in config.export.enabled
                },
            }


# --- helpers ------------------------------------------------------------------------------


def _look_value(value: Any, *, project_look: str | None = None) -> dict[str, Any] | None:
    """A look edit as config data, or None. ``{"name": None}`` means no look: for the
    project None; for a photo, when the project has a look (``project_look``), an override
    of that look at intensity 0 (which grades with no look), else None (no override)."""
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise EditError("look must be an object or null")
    if not value.get("name"):
        if project_look is None:
            return None
        return {"name": project_look, "intensity": 0.0, "parameters": {}}
    return {
        "name": value["name"],
        "intensity": value.get("intensity", 1.0),
        "parameters": dict(value.get("parameters") or {}),
    }


def _photo_metadata(change: Mapping[str, Any]) -> dict[str, Any] | None:
    """A photo ``metadata`` edit as config data. Raises EditError."""
    values = change.get("metadata")
    if not values or "capture_time" not in values:
        return None
    when = values["capture_time"]
    try:
        return {"capture_time": None if not when else parse_clock_time(str(when)).isoformat()}
    except ValueError as error:
        raise EditError(str(error)) from None


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _photo_entry(photos: dict[str, Any], name: str) -> dict[str, Any]:
    folded = name.casefold()
    for key in photos:
        if key.casefold() == folded:
            return photos[key]
    return photos.setdefault(name, {})


def _merge(section: dict[str, Any], values: Mapping[str, Any] | None) -> None:
    for key, value in (values or {}).items():
        if value is None:
            section.pop(key, None)
        else:
            section[key] = value


def _prune(photos: dict[str, Any], name: str) -> None:
    """Drop ``None`` values and empty sections from photo ``name``'s entry, and the entry
    if nothing is left, so the YAML only says what was overridden."""
    for key in list(photos):
        if key.casefold() != name.casefold():
            continue
        entry = photos[key]
        for section in ("grade", "normalise", "metadata"):
            part = entry.get(section)
            if isinstance(part, dict):
                for inner in list(part):
                    if part[inner] is None or part[inner] == {}:
                        del part[inner]
                if not part:
                    del entry[section]
        if not entry:
            del photos[key]


def _validation_message(error: ValidationError) -> str:
    parts = []
    for item in error.errors():
        location = ".".join(str(part) for part in item["loc"])
        parts.append(f"{location}: {item['msg']}")
    return "; ".join(parts)


def _grade_key(config: ProjectConfig) -> str:
    """The grade settings every preview depends on (local contrast, display transform)."""
    return json.dumps(
        {
            "local_contrast": config.grade.local_contrast.model_dump(mode="json"),
            "display_transform": config.grade.display_transform.model_dump(mode="json"),
        },
        sort_keys=True,
    )


def _choice_dict(choice: LookChoice | None) -> dict[str, Any] | None:
    return None if choice is None else choice.model_dump()


def _as_shot(info: PhotoInfo) -> dict[str, float] | None:
    data = info.to_dict()
    kelvin = data.get("as_shot_kelvin")
    tint = data.get("as_shot_tint")
    if kelvin is None:
        return None
    return {"kelvin": round(kelvin), "tint": round(tint or 0.0, 1)}


def _look_dict(look: Look) -> dict[str, Any]:
    return {
        "key": look.key,
        "category": look.file.category,
        "name": look.file.name,
        "description": look.file.description,
        "parameters": {
            key: parameter.model_dump() for key, parameter in look.file.parameters.items()
        },
    }


__all__ = ["LONG_EDGES", "ConfigError", "EditError", "PhotoState", "Session", "Size", "Variant"]
