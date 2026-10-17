"""Tests for rendering one output from the scene image."""

import numpy as np

from picturesq.config import ProjectConfig
from picturesq.pipeline.export import render_output


def _scene() -> np.ndarray:
    rng = np.random.default_rng(11)
    return (rng.random((61, 89, 3), dtype=np.float32) ** 3 * 4.0).astype(np.float32)


def test_render_leaves_the_scene_image_unchanged_by_default() -> None:
    config = ProjectConfig()
    scene = _scene()
    render_output(scene, config.export.outputs["archive"], config.grade.display_transform)
    np.testing.assert_array_equal(scene, _scene())


def test_consuming_a_full_resolution_output_gives_the_same_pixels_in_place() -> None:
    config = ProjectConfig()
    archive, display = config.export.outputs["archive"], config.grade.display_transform
    scene = _scene()
    expected = render_output(scene.copy(), archive, display)
    actual = render_output(scene, archive, display, consume=True)
    np.testing.assert_array_equal(actual, expected)
    # The display transform ran in the scene image's memory instead of a new array.
    assert not np.array_equal(scene, _scene())


def test_consuming_a_resized_output_leaves_the_scene_image_alone() -> None:
    config = ProjectConfig()
    web = config.export.outputs["web"].model_copy(update={"long_edge": 40})
    display = config.grade.display_transform
    scene = _scene()
    expected = render_output(scene, web, display)
    actual = render_output(scene, web, display, consume=True)
    np.testing.assert_array_equal(actual, expected)
    np.testing.assert_array_equal(scene, _scene())
