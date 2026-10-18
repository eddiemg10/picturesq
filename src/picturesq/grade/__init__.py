"""Stage 3, grade: the photo's look and adjustments, local contrast (ADR-0019).

Built-in look files live in `looks/<category>/<name>.yaml`. The look's scene operations
and the adjustments run here, on scene light; its display operations run per output, after
the display transform (``display_operations``).
"""

from picturesq.colour.transfer import FloatArray
from picturesq.config import AdjustmentsConfig, ProjectConfig
from picturesq.config.operations import (
    ContrastOperation,
    ExposureOperation,
    Operation,
    SaturationOperation,
    VibranceOperation,
    WhiteBalanceOperation,
)
from picturesq.grade.local_contrast import local_contrast
from picturesq.grade.operations import apply_operations
from picturesq.photo import UNNAMED, PhotoContext


class LookNotResolvedError(ValueError):
    """A photo has a look, but its context doesn't carry the resolved look."""


def adjustment_operations(adjustments: AdjustmentsConfig) -> list[Operation]:
    """The adjustments as operations, in the order they apply."""
    return [
        ExposureOperation(ev=adjustments.exposure),
        WhiteBalanceOperation(warmth=adjustments.warmth, tint=adjustments.tint),
        ContrastOperation(amount=adjustments.contrast),
        SaturationOperation(amount=adjustments.saturation),
        VibranceOperation(amount=adjustments.vibrance),
    ]


def grade(image: FloatArray, config: ProjectConfig, photo: PhotoContext = UNNAMED) -> FloatArray:
    """Run the grade stage on ``image`` (linear Rec.2020), in place. Returns ``image``.

    The look's scene operations at its intensity, then the photo's adjustments, then local
    contrast. Raises LookNotResolvedError if the photo has a look that ``photo`` doesn't
    carry (build it with ``picturesq.pipeline.export.photo_context``).
    """
    choice = config.photo_look(photo.name)
    look = photo.look
    if choice is not None and (look is None or look.key != choice.name):
        raise LookNotResolvedError(
            f"{photo.name or 'the image'} is graded with {choice.name}, but its context "
            "doesn't carry that look; build it with photo_context"
        )
    return grade_with(image, config, photo, config.photo_adjustments(photo.name))


def grade_with(
    image: FloatArray,
    config: ProjectConfig,
    photo: PhotoContext,
    adjustments: AdjustmentsConfig,
) -> FloatArray:
    """The grade stage with ``photo.look`` and ``adjustments`` as given, whatever the config
    says for the photo (previews of other looks); local contrast and the display transform
    settings come from ``config``. In place; returns ``image``.
    """
    look = photo.look
    if look is not None:
        apply_operations(image, look.operations, look.intensity, "scene", seed=photo.seed)
    apply_operations(image, adjustment_operations(adjustments), 1.0, "scene")
    settings = config.grade
    return local_contrast(image, settings.local_contrast, settings.display_transform)


def display_operations(image: FloatArray, photo: PhotoContext = UNNAMED) -> FloatArray:
    """The photo's look's display-referred operations, on display-linear ``image``, in place."""
    look = photo.look
    if look is not None:
        apply_operations(image, look.operations, look.intensity, "display", seed=photo.seed)
    return image


def has_display_operations(photo: PhotoContext) -> bool:
    """Whether ``display_operations`` would change anything for ``photo``."""
    look = photo.look
    return look is not None and any(
        operation.space == "display" and not operation.scaled(look.intensity).is_neutral()
        for operation in look.operations
    )


__all__ = [
    "LookNotResolvedError",
    "adjustment_operations",
    "display_operations",
    "grade",
    "grade_with",
    "has_display_operations",
    "local_contrast",
]
