"""The grade stage: the photo's look, adjustments, display operations and look checks."""

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from typer.testing import CliRunner

from picturesq.cli import app
from picturesq.config import (
    AdjustmentsConfig,
    LookFileError,
    LookParameterError,
    OutputConfig,
    ProjectConfig,
    SharpenConfig,
)
from picturesq.config.look import Look
from picturesq.config.operations import ContrastOperation, FadeOperation, WhiteBalanceOperation
from picturesq.export import sidecar_document
from picturesq.grade import LookNotResolvedError, grade
from picturesq.grade.operations import apply_operation
from picturesq.photo import PhotoContext
from picturesq.pipeline.export import render_output
from picturesq.pipeline.looks import check_looks, resolve_look

NO_LOCAL_CONTRAST = {"local_contrast": {"enabled": False}}


def _config(grade_section: dict[str, Any], photos: dict[str, Any] | None = None) -> ProjectConfig:
    return ProjectConfig.model_validate(
        {"grade": {**NO_LOCAL_CONTRAST, **grade_section}, "photos": photos or {}}
    )


def _image(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.lognormal(np.log(0.18), 1.0, (24, 32, 3)).astype(np.float32)


def _unsharpened(config: ProjectConfig) -> OutputConfig:
    return config.export.outputs["archive"].model_copy(
        update={"sharpen": SharpenConfig(amount=0.0)}
    )


def _context(config: ProjectConfig, name: str = "a.dng") -> PhotoContext:
    return PhotoContext(name=name, look=resolve_look(config, name))


def test_photo_look_precedence() -> None:
    config = _config(
        {"look": {"name": "cold/test_cool", "intensity": 0.8}},
        {
            "b.dng": {"grade": {"look": {"name": "bw/test_mono"}}},
            "c.dng": {"grade": {"look": {"name": "bw/test_mono", "intensity": 0.0}}},
        },
    )
    project = config.photo_look("a.dng")
    assert project is not None and project.name == "cold/test_cool" and project.intensity == 0.8
    override = config.photo_look("B.DNG")
    assert override is not None and override.name == "bw/test_mono"
    assert config.photo_look("c.dng") is None  # intensity 0: no look
    assert _config({}).photo_look("a.dng") is None


def test_photo_adjustments_replace_only_what_they_set() -> None:
    config = _config(
        {"adjustments": {"warmth": 10, "contrast": 0.1}},
        {"a.dng": {"grade": {"adjustments": {"warmth": -5}}}},
    )
    assert config.photo_adjustments("a.dng") == AdjustmentsConfig(warmth=-5, contrast=0.1)
    assert config.photo_adjustments("b.dng") == AdjustmentsConfig(warmth=10, contrast=0.1)


def test_resolve_look_fills_in_parameters(test_looks: dict[str, Look]) -> None:
    config = _config({"look": {"name": "cold/test_cool", "intensity": 0.5}})
    look = resolve_look(config, "a.dng")
    assert look is not None
    assert look.key == "cold/test_cool" and look.intensity == 0.5
    assert look.parameters == {"fade": 0.05}
    assert look.sha256 == test_looks["cold/test_cool"].sha256
    assert look.operations[0] == WhiteBalanceOperation(warmth=-20)


def test_check_looks_names_the_problem(test_looks: dict[str, Look]) -> None:
    check_looks(_config({"look": {"name": "cold/test_cool"}}))
    with pytest.raises(LookFileError, match="no look called 'cold/nope'"):
        check_looks(_config({}, {"x.dng": {"grade": {"look": {"name": "cold/nope"}}}}))
    with pytest.raises(LookParameterError, match="fade must be between"):
        check_looks(_config({"look": {"name": "cold/test_cool", "parameters": {"fade": 1}}}))


def test_grade_without_a_look_is_bit_identical(test_looks: dict[str, Look]) -> None:
    image = _image()
    for config in (
        _config({}),
        _config({"look": {"name": "cold/test_cool", "intensity": 0.0}}),
    ):
        graded = grade(image.copy(), config, _context(config))
        np.testing.assert_array_equal(graded, image)


def test_grade_applies_the_looks_scene_operations_at_its_intensity(
    test_looks: dict[str, Look],
) -> None:
    config = _config({"look": {"name": "cold/test_cool", "intensity": 0.5}})
    graded = grade(_image(), config, _context(config))
    expected = _image()
    apply_operation(expected, WhiteBalanceOperation(warmth=-10))
    apply_operation(expected, ContrastOperation(amount=0.1))
    np.testing.assert_array_equal(graded, expected)  # fade waits for the display transform


def test_grade_applies_adjustments_after_the_look(test_looks: dict[str, Look]) -> None:
    config = _config(
        {"look": {"name": "cold/test_cool"}, "adjustments": {"exposure": 1.0}},
    )
    graded = grade(_image(), config, _context(config))
    expected = _image()
    apply_operation(expected, WhiteBalanceOperation(warmth=-20))
    apply_operation(expected, ContrastOperation(amount=0.2))
    expected *= 2.0
    np.testing.assert_allclose(graded, expected, rtol=1e-6)


def test_grade_refuses_an_unresolved_look() -> None:
    config = _config({"look": {"name": "cold/test_cool"}})
    with pytest.raises(LookNotResolvedError, match="build it with photo_context"):
        grade(_image(), config, PhotoContext(name="a.dng"))


def test_render_output_runs_display_operations(test_looks: dict[str, Look]) -> None:
    config = _config({"look": {"name": "cold/test_cool"}})
    output = _unsharpened(config)
    display = config.grade.display_transform
    scene = _image()
    plain = render_output(scene, output, display)
    faded = render_output(scene, output, display, photo=_context(config))
    assert faded.min() >= 0.05 * 255 - 1 > plain.min()  # the blacks are lifted
    neutral = _config({"look": {"name": "cold/test_cool", "parameters": {"fade": 0.0}}})
    unfaded = render_output(scene, output, display, photo=_context(neutral))
    np.testing.assert_array_equal(unfaded, plain)  # a neutral display operation is skipped


def test_display_operations_get_the_photos_seed(test_looks: dict[str, Look]) -> None:
    config = _config({"look": {"name": "bw/test_mono"}})
    output = config.export.outputs["archive"]
    display = config.grade.display_transform
    scene = np.full((40, 60, 3), 0.18, dtype=np.float32)
    first = render_output(scene, output, display, photo=_context(config, "a.dng"))
    again = render_output(scene, output, display, photo=_context(config, "A.DNG"))
    other = render_output(scene, output, display, photo=_context(config, "b.dng"))
    np.testing.assert_array_equal(first, again)
    assert not np.array_equal(first, other)


def test_fade_matches_the_operation(test_looks: dict[str, Look]) -> None:
    """The display operation sees the display transform's output, before encoding."""
    from picturesq.colour.agx import AgxCurve, agx
    from picturesq.colour.transfer import srgb_encode
    from picturesq.export import to_8bit

    config = _config({"look": {"name": "cold/test_cool", "intensity": 1.0}})
    output = _unsharpened(config)
    display = config.grade.display_transform
    scene = _image()
    rendered = render_output(scene, output, display, photo=_context(config))
    expected = agx(scene.copy(), AgxCurve.from_config(display))
    apply_operation(expected, FadeOperation(amount=0.05))
    np.testing.assert_array_equal(rendered, to_8bit(srgb_encode(expected)))


def test_sidecar_records_the_look(test_looks: dict[str, Look]) -> None:
    config = _config({"look": {"name": "cold/test_cool", "intensity": 0.7}})
    document = sidecar_document(
        version="1",
        original=Path("a.dng"),
        original_sha256="ab",
        output="web",
        config=config,
        look=resolve_look(config, "a.dng"),
    )
    assert document["look"] == {
        "name": "cold/test_cool",
        "intensity": 0.7,
        "parameters": {"fade": 0.05},
        "sha256": test_looks["cold/test_cool"].sha256,
    }
    assert document["config"]["grade"]["look"]["name"] == "cold/test_cool"
    plain = sidecar_document(
        version="1", original=Path("a.dng"), original_sha256="ab", output="web", config=_config({})
    )
    assert plain["look"] is None


def test_cli_rejects_an_unknown_look(tmp_path: Path, test_looks: dict[str, Look]) -> None:
    (tmp_path / "picturesq.yaml").write_text("grade:\n  look: {name: cold/nope}\n")
    (tmp_path / "a.dng").write_bytes(b"")
    result = CliRunner().invoke(app, ["export", str(tmp_path)])
    assert result.exit_code == 2
    assert "no look called 'cold/nope'" in result.output
