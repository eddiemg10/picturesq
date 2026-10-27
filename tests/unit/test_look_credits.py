"""Every third-party LUT in the look library is credited (ADR-0020)."""

from pathlib import Path

from picturesq.config.look import BUILT_IN_LOOKS, look_library


def test_every_bundled_lut_is_listed_in_the_credits() -> None:
    credits = (BUILT_IN_LOOKS / "CREDITS.md").read_text(encoding="utf-8")
    cubes = sorted(
        path.relative_to(BUILT_IN_LOOKS).as_posix() for path in BUILT_IN_LOOKS.rglob("*.cube")
    )
    assert cubes, "expected bundled LUTs"
    missing = [cube for cube in cubes if f"`{cube}`" not in credits]
    assert not missing, f"add these to looks/CREDITS.md: {missing}"
    assert (BUILT_IN_LOOKS / "LICENSE-CC-BY-4.0.txt").is_file()
    assert (Path(__file__).parents[2] / "NOTICE").is_file()


def test_looks_built_on_a_lut_say_so() -> None:
    for look in look_library().values():
        if any(operation.get("op") == "lut" for operation in look.file.operations):
            assert "CC BY 4.0" in look.file.description, look.key
