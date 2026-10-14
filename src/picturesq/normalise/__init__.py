"""Stage 2, normalise: exposure and chroma noise reduction, per photo.

Pure functions, no IO.
"""

from picturesq.colour.transfer import FloatArray
from picturesq.config import ProjectConfig
from picturesq.normalise.chroma_nr import chroma_noise_reduction
from picturesq.normalise.exposure import apply_exposure, exposure_ev, median_ev


def normalise(image: FloatArray, config: ProjectConfig) -> FloatArray:
    """Run the normalise stage on ``image`` (linear Rec.2020), in place. Returns ``image``."""
    settings = config.normalise
    if not settings.enabled:
        return image
    apply_exposure(image, exposure_ev(image, settings.exposure), out=image)
    return chroma_noise_reduction(image, settings.chroma_nr)


__all__ = ["apply_exposure", "chroma_noise_reduction", "exposure_ev", "median_ev", "normalise"]
