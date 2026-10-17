# Dependencies

What each dependency is and why picturesq needs it. The approved list and milestones are in
[project plan §12](project-plan.md#12-dependencies-proposed-additions-need-approval). Update this
file in the same PR as any dependency change.

## Runtime

| Package | What it is | Why we need it | Added in |
|---|---|---|---|
| typer | CLI framework | The `picturesq` command and its subcommands. | M0 |
| rawpy | Python binding for LibRaw | Decodes RAW/DNG files to scene-linear data ([ADR 0001](decisions/0001-rawpy-decoder-no-darktable.md)). | M1 |
| numpy | N-dimensional arrays | All image maths: float32 `HxWx3` arrays, in-place operations. | M1 |
| pydantic | Data validation | Config models and the printable config schema. | M1 |
| pyyaml | YAML reader/writer | Reads and writes the project and look files ([ADR 0004](decisions/0004-yaml-machine-owned.md)). | M1 |
| pillow | Imaging library | Final 8-bit sRGB JPEG export, ICC profile embedding (needs LittleCMS), EXIF and resize. | M1 |
| tifffile | TIFF reader/writer for numpy | 16-bit RGB TIFF intermediates, written only with `--full-res` (decision D13). Pillow's 16-bit RGB TIFF support is weak. | M1 |
| starlette + uvicorn | Web framework and server | Local web UI (`picturesq ui`). | M4 |
| watchfiles | File watcher | Live reload when the YAML config changes. | M4 |

Pillow only touches the final step: everything before it stays in float32 scene-linear, and we
convert to 8-bit only when handing the array to Pillow.

## Dev only

| Package | Why |
|---|---|
| pytest | Test runner. |
| hypothesis | Property-based tests for the colour and normalise maths. |
| colour-science | Test oracle: our colour maths is checked against it. Never imported by `src/`. |
| types-pyyaml | Type stubs so pyright can check YAML code. |
| jsonschema | Checks that `picturesq schema` is a valid JSON Schema and that the documented config validates against it. |
| ruff | Lint and format. |
| pyright | Type checking. |
| pre-commit | Git hooks (including the large-file check). |
| pytest-benchmark | Planned: performance tests. Not yet in `pyproject.toml`. |
| playwright | Planned for M4: UI tests. Not yet in `pyproject.toml`. |

## Smoke test

`tests/unit/test_dependencies.py` checks on every CI OS that LibRaw loads through rawpy (≥ 0.21)
and that Pillow has JPEG and LittleCMS support.
