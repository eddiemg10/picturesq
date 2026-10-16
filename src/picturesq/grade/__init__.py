"""Stage 3, grade: operations, look files, intensity, adjustments, LUTs, look library.

Built-in look files live in `looks/<category>/<name>.yaml`. v0 runs local contrast only.
"""

from picturesq.colour.transfer import FloatArray
from picturesq.config import ProjectConfig
from picturesq.grade.local_contrast import local_contrast


def grade(image: FloatArray, config: ProjectConfig) -> FloatArray:
    """Run the grade stage on ``image`` (linear Rec.2020), in place. Returns ``image``."""
    settings = config.grade
    return local_contrast(image, settings.local_contrast, settings.display_transform)


__all__ = ["grade", "local_contrast"]
