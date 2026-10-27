"""What the stages know about the photo they render, besides its pixels."""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field

from picturesq.config.operations import Operation
from picturesq.decode.info import PhotoInfo


@dataclass(frozen=True)
class ResolvedLook:
    """A photo's look, ready to apply: its operations with parameter values filled in.

    ``key`` is ``category/name``, ``sha256`` the look file's hash, ``parameters`` every
    parameter's value (defaults included): together with ``intensity`` enough to say
    exactly what was applied (the sidecar records them).
    """

    key: str
    sha256: str
    intensity: float
    parameters: Mapping[str, float]
    operations: tuple[Operation, ...]


@dataclass(frozen=True)
class PhotoContext:
    """The photo an image belongs to. Pure data: stages read it, never files.

    ``name`` is the original's file name, which keys the photo's overrides in config
    (``ProjectConfig.photo``). ``info`` is its photo info (``read_photo_info``), or None
    when it wasn't read: the pipeline reads it only when a stage needs it (today, a
    ``wb_kelvin`` / ``tint`` override, which starts from the as-shot white). ``look`` is
    the photo's resolved look (``picturesq.pipeline.looks``), None for no look.
    """

    name: str
    info: PhotoInfo | None = None
    look: ResolvedLook | None = field(default=None)

    @property
    def seed(self) -> int:
        """The photo's seed for operations with randomness (grain): from its name, ignoring
        case, so a photo gets the same grain on every run and every OS."""
        digest = hashlib.sha256(self.name.casefold().encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "little")


UNNAMED = PhotoContext(name="")
"""For images that aren't a project's photo (tests, figures): no overrides apply."""
