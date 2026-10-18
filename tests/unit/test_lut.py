"""LUTs: .cube parsing, tetrahedral interpolation (colour-science oracle), the lut operation."""

import hashlib
from pathlib import Path

import colour
import numpy as np
import pytest
import yaml
from colour.algebra import table_interpolation_tetrahedral
from pydantic import ValidationError

from picturesq.colour.lut import CubeError, Lut, apply_lut, apply_lut_3d, parse_cube
from picturesq.colour.transfer import srgb_decode, srgb_encode
from picturesq.config import LookFileError, load_look_file
from picturesq.config.operations import LutOperation
from picturesq.grade.operations import LutNotLoadedError, apply_operation


def _identity_table(size: int) -> np.ndarray:
    grid = np.linspace(0.0, 1.0, size, dtype=np.float32)
    b, g, r = np.meshgrid(grid, grid, grid, indexing="ij")
    return np.stack([r, g, b], axis=-1)


def _cube_text(table: np.ndarray, header: str = "") -> str:
    size = table.shape[0]
    rows = "\n".join(" ".join(f"{v:.6f}" for v in rgb) for rgb in table.reshape(-1, 3))
    return f'TITLE "test"\n# a comment\n{header}LUT_3D_SIZE {size}\n{rows}\n'


def _oracle(table: np.ndarray, pixels: np.ndarray, domain: np.ndarray | None = None) -> np.ndarray:
    rgb_table = table.transpose(2, 1, 0, 3).astype(np.float64)
    lut = (
        colour.LUT3D(table=rgb_table)
        if domain is None
        else colour.LUT3D(table=rgb_table, domain=domain)
    )
    return lut.apply(pixels.astype(np.float64), interpolator=table_interpolation_tetrahedral)


def test_parse_cube_reads_3d() -> None:
    table = np.random.default_rng(0).random((5, 5, 5, 3)).astype(np.float32)
    lut = parse_cube(_cube_text(table))
    assert lut.is_3d and lut.size == 5 and lut.title == "test"
    np.testing.assert_allclose(lut.table, table, atol=1e-6)


def test_parse_cube_reads_1d_and_domain() -> None:
    text = "LUT_1D_SIZE 3\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 2 2 2\n0 0 0\n0.25 0.5 0.75\n1 1 1\n"
    lut = parse_cube(text)
    assert not lut.is_3d
    np.testing.assert_array_equal(lut.domain_max, [2, 2, 2])
    out = apply_lut(np.array([[1.0, 1.0, 1.0], [0.5, 3.0, -1.0]], dtype=np.float32), lut)
    np.testing.assert_allclose(out, [[0.25, 0.5, 0.75], [0.125, 1.0, 0.0]], atol=1e-6)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("0 0 0\n", "no LUT_1D_SIZE or LUT_3D_SIZE"),
        ("LUT_3D_SIZE 2\n0 0 0\n", "expected 8 entries for size 2, got 1"),
        ("LUT_3D_SIZE 2\n0 0\n", "line 2: expected 3 numbers, got 2"),
        ("LUT_3D_SIZE 2\n0 zero 0\n", "line 2: cannot read"),
        ("LUT_3D_SIZE 2\nGAMMA 2.2\n", "line 2: unknown keyword 'GAMMA'"),
        ("LUT_3D_SIZE 99\n", "line 1: LUT_3D_SIZE must be 2 to 65"),
        ("LUT_3D_SIZE 2\nLUT_1D_SIZE 2\n", "line 2: more than one LUT size"),
        ("DOMAIN_MAX 0 0 0\nLUT_1D_SIZE 2\n0 0 0\n1 1 1\n", "min below max"),
    ],
)
def test_parse_cube_errors(text: str, message: str) -> None:
    with pytest.raises(CubeError, match=message):
        parse_cube(text)


@pytest.mark.parametrize("size", [2, 17, 33])
def test_identity_lut_is_identity(size: int) -> None:
    pixels = np.random.default_rng(1).random((2000, 3)).astype(np.float32)
    out = apply_lut_3d(pixels, Lut(_identity_table(size)))
    np.testing.assert_allclose(out, pixels, atol=1e-6)


@pytest.mark.parametrize("size", [2, 9, 17])
def test_matches_colour_science_tetrahedral(size: int) -> None:
    rng = np.random.default_rng(size)
    table = rng.random((size, size, size, 3)).astype(np.float32)
    pixels = rng.random((5000, 3)).astype(np.float32)
    np.testing.assert_allclose(apply_lut_3d(pixels, Lut(table)), _oracle(table, pixels), atol=1e-5)


def test_matches_colour_science_with_a_domain_and_clamps_outside() -> None:
    rng = np.random.default_rng(3)
    table = rng.random((9, 9, 9, 3)).astype(np.float32)
    domain = np.array([[0.0, 0.0, 0.0], [2.0, 1.0, 4.0]])
    lut = Lut(table, domain[0].astype(np.float32), domain[1].astype(np.float32))
    pixels = (rng.random((3000, 3)) * domain[1]).astype(np.float32)
    np.testing.assert_allclose(apply_lut_3d(pixels, lut), _oracle(table, pixels, domain), atol=1e-5)
    outside = np.array([[-1.0, 5.0, 9.0]], dtype=np.float32)
    clamped = np.array([[0.0, 1.0, 4.0]], dtype=np.float32)
    np.testing.assert_allclose(apply_lut_3d(outside, lut), apply_lut_3d(clamped, lut), atol=1e-6)


def test_greys_stay_grey_between_grid_points() -> None:
    """Tetrahedral interpolation uses only grey-diagonal corners for a grey input."""
    rng = np.random.default_rng(4)
    table = rng.random((9, 9, 9, 3)).astype(np.float32)
    for i in range(9):
        table[i, i, i] = table[i, i, i].mean()
    greys = np.repeat(rng.random((500, 1)), 3, axis=1).astype(np.float32)
    out = apply_lut_3d(greys, Lut(table))
    assert np.ptp(out, axis=1).max() < 1e-6


def _loaded(table: np.ndarray, **fields: object) -> LutOperation:
    return LutOperation(file="look.cube", **fields).with_table(Lut(table))  # type: ignore[arg-type]


@pytest.mark.parametrize("space", ["srgb", "rec709"])
def test_identity_lut_operation_keeps_the_image(space: str) -> None:
    image = np.random.default_rng(5).random((20, 30, 3)).astype(np.float32)
    before = image.copy()
    apply_operation(image, _loaded(_identity_table(33), input_space=space))
    np.testing.assert_allclose(image, before, atol=1e-5)


def test_lut_runs_in_its_input_space() -> None:
    """A LUT that halves sRGB values halves the encoded value, not the linear one."""
    halve = _identity_table(17) * 0.5
    image = srgb_decode(np.full((2, 2, 3), 0.8, dtype=np.float32))
    apply_operation(image, _loaded(halve))
    np.testing.assert_allclose(srgb_encode(image), 0.4, atol=1e-5)


def test_lut_amount_and_intensity_blend() -> None:
    halve = _identity_table(17) * 0.5
    for amount, intensity, expected in [(0.5, 1.0, 0.6), (1.0, 0.5, 0.6), (1.0, 1.5, 0.2)]:
        image = srgb_decode(np.full((2, 2, 3), 0.8, dtype=np.float32))
        apply_operation(image, _loaded(halve, amount=amount), intensity)
        np.testing.assert_allclose(srgb_encode(image), expected, atol=1e-5)


def test_unloaded_lut_is_an_error() -> None:
    with pytest.raises(LutNotLoadedError, match=r"look\.cube"):
        apply_operation(np.zeros((2, 2, 3), np.float32), LutOperation(file="look.cube"))


@pytest.mark.parametrize("file", ["../other.cube", "a//b.cube", "./a.cube", "look.png"])
def test_lut_file_must_be_inside_the_looks_folder(file: str) -> None:
    with pytest.raises(ValidationError):
        LutOperation(file=file)


def _look_with_lut(directory: Path, cube: str | None) -> Path:
    look = {
        "name": "filmic",
        "category": "cinematic",
        "description": "A LUT look",
        "operations": [{"op": "lut", "file": "luts/filmic.cube", "amount": 0.8}],
    }
    path = directory / "cinematic" / "filmic.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(look), encoding="utf-8")
    if cube is not None:
        (path.parent / "luts").mkdir()
        (path.parent / "luts" / "filmic.cube").write_text(cube, encoding="utf-8")
    return path


def test_look_file_loads_its_lut_and_hashes_it(tmp_path: Path) -> None:
    cube = _cube_text(_identity_table(5))
    path = _look_with_lut(tmp_path, cube)
    look = load_look_file(path)
    (operation,) = look.resolve()
    assert isinstance(operation, LutOperation) and operation.table is not None
    expected = hashlib.sha256(path.read_bytes() + cube.encode("utf-8")).hexdigest()
    assert look.sha256 == expected


def test_look_file_lut_errors(tmp_path: Path) -> None:
    with pytest.raises(LookFileError, match=r"cannot read its LUT luts/filmic\.cube"):
        load_look_file(_look_with_lut(tmp_path / "missing", None))
    with pytest.raises(LookFileError, match=r"its LUT luts/filmic\.cube is invalid: line 1"):
        load_look_file(_look_with_lut(tmp_path / "broken", "LUT_3D_SIZE two\n"))
