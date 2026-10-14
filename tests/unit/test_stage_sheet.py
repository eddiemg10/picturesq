"""Pure helpers behind scripts/stage_sheet.py."""

import numpy as np
import pytest

from picturesq.preview.stage_sheet import (
    MARKER_END,
    MARKER_START,
    Panel,
    compose_sheet,
    mark_clipped,
    panel_stats,
    preview_section,
    replace_section,
    sheet_size,
    validate_sample_name,
)

LISTED = ["dji-fc4382.dng", "sony-ilme-fx3.arw"]


def _section(tag: str) -> str:
    return preview_section(f"https://example.invalid/{tag}.jpg", f"caption {tag}", "| t |")


def test_section_appended_when_absent() -> None:
    body = "## Why\n\nBecause."
    out = replace_section(body, _section("a"))
    assert out.startswith(body + "\n\n" + MARKER_START)
    assert out.count("## Preview") == 1


def test_section_into_empty_body() -> None:
    assert replace_section("", _section("a")).startswith(MARKER_START)


def test_section_replaced_and_surroundings_kept() -> None:
    before = replace_section("intro\n", _section("a")) + "\n## Checklist\n- [ ] x\n"
    out = replace_section(before, _section("b"))
    assert "a.jpg" not in out
    assert "b.jpg" in out
    assert out.startswith("intro\n")
    assert out.endswith("\n## Checklist\n- [ ] x\n")
    assert out.count(MARKER_START) == out.count(MARKER_END) == 1


def test_section_replace_is_idempotent() -> None:
    once = replace_section("intro", _section("a"))
    assert replace_section(once, _section("a")) == once


def test_valid_name_accepted() -> None:
    assert validate_sample_name("dji-fc4382.dng", LISTED) == "dji-fc4382.dng"


@pytest.mark.parametrize(
    "name",
    [
        "../reference/raw/x.DNG",
        "/etc/passwd",
        "/abs/dji-fc4382.dng",
        "reference/samples/dji-fc4382.dng",
        "..\\dji-fc4382.dng",
        "",
        "..",
        "unlisted.dng",
        "DJI-FC4382.DNG",
    ],
)
def test_bad_names_rejected(name: str) -> None:
    with pytest.raises(ValueError):
        validate_sample_name(name, LISTED)


def test_all_white_is_fully_clipped() -> None:
    stats = panel_stats(Panel("w", np.full((10, 20, 3), 255, dtype=np.uint8)))
    assert stats.clipped_percent == 100.0
    assert stats.median_luminance == pytest.approx(1.0, abs=1e-4)
    assert (stats.width, stats.height) == (20, 10)


def test_mid_grey_median_and_no_clipping() -> None:
    # sRGB 188/255 decodes to about 0.5 display-linear.
    stats = panel_stats(Panel("g", np.full((8, 8, 3), 188, dtype=np.uint8)))
    assert stats.clipped_percent == 0.0
    assert stats.median_luminance == pytest.approx(0.503, abs=0.01)


def test_mark_clipped_paints_magenta_without_touching_input() -> None:
    pixels = np.zeros((2, 2, 3), dtype=np.uint8)
    pixels[0, 0] = (255, 10, 10)
    marked = mark_clipped(pixels)
    assert tuple(marked[0, 0]) == (255, 0, 255)
    assert tuple(marked[1, 1]) == (0, 0, 0)
    assert tuple(pixels[0, 0]) == (255, 10, 10)


@pytest.mark.parametrize("count", [1, 3, 4, 5, 6])
def test_compose_size_matches_layout(count: int) -> None:
    panels = [Panel(f"p{i}", np.full((30, 40, 3), 90, dtype=np.uint8)) for i in range(count)]
    sheet = compose_sheet("title", panels, (50, 40))
    assert sheet.size == sheet_size(count, (50, 40))
    columns = min(3, count)
    assert sheet.width == 10 + columns * 60
    rows = -(-count // 3)
    assert sheet.height == 38 + rows * (28 + 40 + 10)


def _synthetic_measure(ev: float) -> float:
    """A non-linear, rising 'render': median of a clipped tone-mapped ramp."""
    from picturesq.colour.transfer import srgb_encode
    from picturesq.preview.stage_sheet import median_luminance

    ramp = np.linspace(0.01, 1.0, 2000, dtype=np.float32)
    scene = np.repeat(ramp[:, None], 3, axis=1).reshape(40, 50, 3) * np.float32(2.0**ev)
    display = np.clip(scene / (1.0 + scene), 0.0, 1.0)  # stand-in display transform
    return median_luminance(np.round(srgb_encode(display) * 255.0).astype(np.uint8))


def test_match_exposure_reproduces_target() -> None:
    from picturesq.preview.stage_sheet import match_exposure

    target = _synthetic_measure(1.3)
    found = match_exposure(_synthetic_measure, target)
    assert not found.clamped
    assert found.ev == pytest.approx(1.3, abs=0.05)
    assert found.achieved == pytest.approx(target, abs=0.01)


def test_match_exposure_is_monotonic_in_target() -> None:
    from picturesq.preview.stage_sheet import match_exposure

    targets = [0.05, 0.1, 0.2, 0.3, 0.4]
    evs = [match_exposure(_synthetic_measure, t).ev for t in targets]
    assert evs == sorted(evs)
    assert len(set(evs)) == len(evs)


def test_match_exposure_clamps_unreachable_targets() -> None:
    from picturesq.preview.stage_sheet import match_exposure, stats_table

    high = match_exposure(_synthetic_measure, 2.0)
    low = match_exposure(_synthetic_measure, -0.1, lo=-1.0, hi=1.0)
    assert (high.ev, high.clamped) == (6.0, True)
    assert (low.ev, low.clamped) == (-1.0, True)
    assert "clamped" in stats_table([], 0.0, 0.0, high)
    assert "+6.00 EV" in stats_table([], 0.0, 0.0, high)
