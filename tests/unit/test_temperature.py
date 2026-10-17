"""Colour temperature (Robertson) and Bradford adaptation, checked against colour-science."""

import colour
import numpy as np
import pytest
from colour.temperature import robertson1968

from picturesq.colour.temperature import _ROBERTSON, bradford_matrix, xy_to_cct, xy_to_xyz


def test_isotemperature_table_matches_colour_science() -> None:
    expected = np.array(robertson1968.DATA_ISOTEMPERATURE_LINES_ROBERTSON1968)
    assert np.allclose(_ROBERTSON, expected, atol=0, rtol=0)


@pytest.mark.parametrize(
    "xy",
    [
        (0.3127, 0.3290),
        (0.44757, 0.40745),
        (0.3457, 0.3585),
        (0.28, 0.29),
        (0.38, 0.38),
        (0.50, 0.41),
    ],
)
def test_cct_matches_colour_science(xy: tuple[float, float]) -> None:
    uv = colour.xy_to_UCS_uv(np.array(xy))
    expected = robertson1968.uv_to_CCT_Robertson1968(uv)[0]
    assert xy_to_cct(xy) == pytest.approx(expected, rel=1e-6)


def test_bradford_maps_white_to_white_and_matches_colour_science() -> None:
    a, d65 = (0.44757, 0.40745), (0.3127, 0.3290)
    matrix = bradford_matrix(a, d65)
    assert np.allclose(matrix @ xy_to_xyz(a), xy_to_xyz(d65), atol=1e-12)
    expected = colour.adaptation.matrix_chromatic_adaptation_VonKries(
        xy_to_xyz(a), xy_to_xyz(d65), transform="Bradford"
    )
    assert np.allclose(matrix, expected, atol=1e-9)
