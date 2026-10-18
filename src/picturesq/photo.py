"""What the scene stages know about the photo they render, besides its pixels."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PhotoContext:
    """The photo an image belongs to. Pure data: stages read it, never files.

    ``name`` is the original's file name, which keys the photo's overrides in config
    (``ProjectConfig.photo``).
    """

    name: str


UNNAMED = PhotoContext(name="")
"""For images that aren't a project's photo (tests, figures): no overrides apply."""
