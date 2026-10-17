"""Correlated colour temperature (CCT) and chromatic adaptation (pure maths, float64).

**CCT** places a white on the line of black-body (Planckian) colours: tungsten is ~2850 K,
daylight ~5500-6500 K. Robertson's (1968) method interpolates between 31 isotemperature
lines in the CIE 1960 uv diagram; the Adobe DNG SDK uses it to decide how far a photo's
white lies between a camera's two calibration illuminants, so we do too.

**Chromatic adaptation** (Bradford) maps colours seen under one white to the colours that
look the same under another, by scaling cone-like responses: how our eyes adapt to the
colour of the light. ICC and the DNG specification both use Bradford.
"""

import numpy as np
from numpy.typing import NDArray

Matrix = NDArray[np.float64]

# Robertson's isotemperature lines: (reciprocal megakelvin, u, v, slope), from Wyszecki &
# Stiles, "Color Science" (1982), table 1(3.11). Public data.
_ROBERTSON = np.array(
    [
        (0, 0.18006, 0.26352, -0.24341),
        (10, 0.18066, 0.26589, -0.25479),
        (20, 0.18133, 0.26846, -0.26876),
        (30, 0.18208, 0.27119, -0.28539),
        (40, 0.18293, 0.27407, -0.30470),
        (50, 0.18388, 0.27709, -0.32675),
        (60, 0.18494, 0.28021, -0.35156),
        (70, 0.18611, 0.28342, -0.37915),
        (80, 0.18740, 0.28668, -0.40955),
        (90, 0.18880, 0.28997, -0.44278),
        (100, 0.19032, 0.29326, -0.47888),
        (125, 0.19462, 0.30141, -0.58204),
        (150, 0.19962, 0.30921, -0.70471),
        (175, 0.20525, 0.31647, -0.84901),
        (200, 0.21142, 0.32312, -1.0182),
        (225, 0.21807, 0.32909, -1.2168),
        (250, 0.22511, 0.33439, -1.4512),
        (275, 0.23247, 0.33904, -1.7298),
        (300, 0.24010, 0.34308, -2.0637),
        (325, 0.24792, 0.34655, -2.4681),
        (350, 0.25591, 0.34951, -2.9641),
        (375, 0.26400, 0.35200, -3.5814),
        (400, 0.27218, 0.35407, -4.3633),
        (425, 0.28039, 0.35577, -5.3762),
        (450, 0.28863, 0.35714, -6.7262),
        (475, 0.29685, 0.35823, -8.5955),
        (500, 0.30505, 0.35907, -11.324),
        (525, 0.31320, 0.35968, -15.628),
        (550, 0.32129, 0.36011, -23.325),
        (575, 0.32931, 0.36038, -40.770),
        (600, 0.33724, 0.36051, -116.45),
    ]
)

BRADFORD: Matrix = np.array(
    [
        [0.8951, 0.2664, -0.1614],
        [-0.7502, 1.7135, 0.0367],
        [0.0389, -0.0685, 1.0296],
    ]
)
"""XYZ → Bradford cone-like responses (Lam 1985), as used by ICC and the DNG specification."""


def xy_to_xyz(xy: tuple[float, float]) -> NDArray[np.float64]:
    """Chromaticity → XYZ with luminance Y = 1."""
    x, y = xy
    return np.array([x / y, 1.0, (1.0 - x - y) / y])


def xyz_to_xy(xyz: NDArray[np.float64]) -> tuple[float, float]:
    total = float(np.sum(xyz))
    return float(xyz[0]) / total, float(xyz[1]) / total


def xy_to_cct(xy: tuple[float, float]) -> float:
    """Correlated colour temperature in kelvin (Robertson 1968), clamped to [1667, inf).

    Whites bluer than the first isotemperature line (infinite temperature) return a very
    large value; whites redder than the last (1667 K) return 1667.
    """
    x, y = xy
    denominator = -2.0 * x + 12.0 * y + 3.0
    u, v = 4.0 * x / denominator, 6.0 * y / denominator
    mired, line_u, line_v, slope = _ROBERTSON.T
    # Signed distance from each isotemperature line; the white lies between two lines
    # where the sign flips.
    distance = ((v - line_v) - slope * (u - line_u)) / np.sqrt(1.0 + slope**2)
    flips = np.nonzero(distance[1:] * distance[:-1] <= 0.0)[0]
    if len(flips) == 0:
        return 1e6 / mired[-1] if distance[-1] > 0.0 else 1e9
    i = int(flips[0])
    fraction = distance[i] / (distance[i] - distance[i + 1])
    reciprocal = mired[i] + fraction * (mired[i + 1] - mired[i])
    return 1e6 / reciprocal if reciprocal > 0.0 else 1e9


def bradford_matrix(source_white: tuple[float, float], target_white: tuple[float, float]) -> Matrix:
    """XYZ under ``source_white`` → corresponding XYZ under ``target_white`` (Bradford)."""
    source = BRADFORD @ xy_to_xyz(source_white)
    target = BRADFORD @ xy_to_xyz(target_white)
    return np.linalg.inv(BRADFORD) @ np.diag(target / source) @ BRADFORD
