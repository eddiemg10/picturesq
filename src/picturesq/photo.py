"""What the scene stages know about the photo they render, besides its pixels."""

from dataclasses import dataclass

from picturesq.decode.info import PhotoInfo


@dataclass(frozen=True)
class PhotoContext:
    """The photo an image belongs to. Pure data: stages read it, never files.

    ``name`` is the original's file name, which keys the photo's overrides in config
    (``ProjectConfig.photo``). ``info`` is its photo info (``read_photo_info``), or None
    when it wasn't read: the pipeline reads it only when a stage needs it (today, a
    ``wb_kelvin`` / ``tint`` override, which starts from the as-shot white).
    """

    name: str
    info: PhotoInfo | None = None


UNNAMED = PhotoContext(name="")
"""For images that aren't a project's photo (tests, figures): no overrides apply."""
