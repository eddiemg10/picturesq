import struct

import numpy as np
import pytest

from picturesq.decode.opcodes import (
    GAIN_MAP,
    WARP_RECTILINEAR,
    GainMap,
    LensCorrections,
    WarpRectilinear,
    apply_lens_corrections,
    gain_at,
    parse_opcode_list,
)


def _gain_map_bytes(
    gains: np.ndarray, area: tuple[int, int, int, int] = (0, 0, 10**6, 10**6)
) -> bytes:
    points_v, points_h, planes = gains.shape
    body = struct.pack(">10I", *area, 0, 3, 1, 1, points_v, points_h)
    body += struct.pack(">4d", 1.0 / max(1, points_v - 1), 1.0 / max(1, points_h - 1), 0.0, 0.0)
    body += struct.pack(">I", planes) + gains.astype(">f4").tobytes()
    return struct.pack(">IIII", GAIN_MAP, 0x01030000, 0, len(body)) + body


def _warp_bytes(coefficients: list[float], centre: tuple[float, float] = (0.5, 0.5)) -> bytes:
    body = struct.pack(">I", 1) + struct.pack(">8d", *coefficients, *centre)
    return struct.pack(">IIII", WARP_RECTILINEAR, 0x01030000, 0, len(body)) + body


def _list(*opcodes: bytes) -> bytes:
    return struct.pack(">I", len(opcodes)) + b"".join(opcodes)


def test_parse_gain_map_warp_and_unsupported() -> None:
    gains = np.arange(12, dtype=np.float32).reshape(2, 3, 2)
    other = struct.pack(">IIII", 4, 0, 0, 4) + b"\0\0\0\0"
    parsed = parse_opcode_list(
        _list(_gain_map_bytes(gains), _warp_bytes([1, 0.1, 0, 0, 0, 0]), other)
    )
    gain_map, warp = parsed.opcodes
    assert isinstance(gain_map, GainMap) and isinstance(warp, WarpRectilinear)
    np.testing.assert_array_equal(gain_map.gains, gains)
    assert warp.coefficients.shape == (1, 6) and warp.coefficients[0, 1] == pytest.approx(0.1)
    assert parsed.unsupported == (4,)


def test_gain_at_interpolates_and_clamps() -> None:
    gain_map = parse_opcode_list(_list(_gain_map_bytes(np.array([[[1.0], [3.0]]])))).opcodes[0]
    assert isinstance(gain_map, GainMap)
    x = np.array([-0.5, 0.0, 0.5, 1.0, 2.0])
    np.testing.assert_allclose(gain_at(gain_map, np.zeros_like(x), x)[:, 0], [1, 1, 2, 3, 3])


def _image() -> np.ndarray:
    rng = np.random.default_rng(0)
    return (rng.random((30, 40, 3)) * 60000).astype(np.uint16)


def test_no_op_corrections_are_identity_and_scaled() -> None:
    source = _image()
    identity = parse_opcode_list(
        _list(_gain_map_bytes(np.ones((3, 3, 1), np.float32)), _warp_bytes([1, 0, 0, 0, 0, 0]))
    )
    out = apply_lens_corrections(source, identity, 0.5)
    np.testing.assert_allclose(out, source * 0.5, rtol=1e-5)


def test_uniform_gain_multiplies() -> None:
    corrections = parse_opcode_list(_list(_gain_map_bytes(np.full((2, 2, 1), 2.0, np.float32))))
    out = apply_lens_corrections(_image(), corrections, 1.0)
    np.testing.assert_allclose(out, _image() * 2.0, rtol=1e-5)


def test_gain_map_area_limits_effect() -> None:
    corrections = parse_opcode_list(
        _list(_gain_map_bytes(np.full((2, 2, 1), 2.0, np.float32), area=(0, 0, 10, 40)))
    )
    out = apply_lens_corrections(_image(), corrections, 1.0)
    np.testing.assert_allclose(out[:10], _image()[:10] * 2.0, rtol=1e-5)
    np.testing.assert_allclose(out[10:], _image()[10:], rtol=1e-5)


def test_radial_warp_samples_outward_for_positive_kr1() -> None:
    """kr1 > 0: each output pixel reads from further out, so the image shrinks toward the centre."""
    source = np.zeros((41, 41, 3), np.float32)
    source[20, 36] = 1.0  # a dot right of centre
    warp = WarpRectilinear(np.array([[1.0, 0.2, 0, 0, 0, 0]]), (0.5, 0.5))
    out = apply_lens_corrections(source, LensCorrections((warp,), ()), 1.0)
    column = int(np.argmax(out[20, :, 0]))
    assert 20 < column < 36
