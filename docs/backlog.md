# Backlog seed: M0 and M1

Source for the GitHub issues. Each task is 30–60 min, with acceptance criteria (AC) and a test plan (T).
Label `learn` = a good one for the user to implement personally. Later milestones are broken down at the end of the previous one.

## M0 — Setup

1. **Claim PyPI name `picturesq`**: add a pending trusted publisher on PyPI. AC: pending publisher visible in PyPI account. T: screenshot / link in the issue.
2. **Connect agents**: `/install-github-app` (Claude), connect Codex cloud, add Figma MCP. AC: `@claude` replies on a test issue; Codex sees the repo; `claude mcp list` shows figma. T: links in the issue.
3. **Shoot the Pocket 4 reference set**: scenarios R01–R10 (`reference/README.md`), DNG+JPEG if possible. AC: 10 scenarios in `reference/raw/` + `manifest.yaml`. T: `ls` + manifest review.
4. **Inspect Pocket 4 DNG structure** `learn`: use `exiftool` / rawpy to answer: Bayer or linear DNG? Bit depth, black/white levels, embedded matrices, opcodes, lens-correction tags, embedded preview size. AC: findings appended to the learning log + project plan §14 answered. T: a script in `scripts/inspect_raw.py` prints the summary.
5. **Can the Pocket 4 shoot DNG+JPEG together?** AC: answer recorded in project plan §14. T: camera menu check.
6. **Select CC0 sample RAWs**: pick 3–4 small CC0 files from raw.pixls.us (Bayer CR2/NEF, X-Trans RAF, a DNG). AC: `reference/samples.json` populated with URLs + sha256; `scripts/fetch_samples.py` downloads and verifies. T: run the script twice (second run all "ok").
7. **Licence audit: AgX + LUT packs**: check the licences of AgX reference implementations (Blender, darktable, AgXc) and the RawTherapee film-sim HaldCLUTs. AC: table in `docs/decisions/0006-asset-licences.md`: what we can port or bundle. T: review.
8. **Sign off project plan**: user reads `docs/project-plan.md`, comments, approves. AC: open questions resolved or deferred explicitly. T: PR merged with edits.

## M1 — Develop & export (neutral render)

1. **Add M1 runtime deps** (rawpy, numpy, pillow, tifffile, pydantic, pyyaml). AC: `uv sync` on Linux + Windows CI green. T: CI.
2. **Transfer functions** `learn`: sRGB encode/decode, linear ↔ log2 helpers in `color/transfer.py`. AC: round-trip error < 1e-6; matches colour-science. T: hypothesis + oracle tests.
3. **Colour space matrices**: Rec.2020 ↔ sRGB/Rec.709 linear, XYZ. AC: matrices match colour-science to 1e-6; white maps to white. T: oracle tests.
4. **Project config model v0**: pydantic `ProjectConfig` with `develop` + `export` sections, YAML load/save (atomic write), defaults. AC: round-trip YAML; invalid config gives a clear error (exit 2). T: unit tests.
5. **`picturesq schema`**: prints the JSON Schema for the project config. AC: valid JSON Schema; snapshot test. T: CLI test.
6. **RAW discovery**: find supported RAW files in a dir (extensions from LibRaw, case-insensitive), ignoring `.picturesq/` and `exports/`. AC: deterministic sorted list. T: unit test with temp dir.
7. **Decode to scene-linear**: `io/decode.py` uses rawpy into linear Rec.2020 float32 (gamma 1, no auto-bright, camera WB). AC: output dtype/shape; a grey patch stays neutral on a CC0 sample. T: integration test.
8. **Proxy generation + cache**: `half_size` decode → 2048 px float16 `.npy` keyed by content hash. AC: second run is a cache hit; a config change invalidates. T: unit + integration.
9. **AgX display transform v1** `learn`: implement from the published maths in `color/agx.py`. AC: monotonic; mid-grey maps to the expected value; no hue flips on a saturated ramp. T: property tests + a ramp image in goldens.
10. **sRGB JPEG export**: Pillow, embedded sRGB ICC, quality + long-edge resize from the export profile. AC: output opens with the correct profile; dimensions correct. T: unit test.
11. **Copy EXIF to exports**: capture time, camera, lens, exposure. AC: exiftool shows the fields. T: integration test.
12. **Export sidecar**: `<name>.picturesq.json` with resolved config, version, input hash. AC: reproducible (identical across two runs). T: unit test.
13. **`develop` + `export` + `run` commands (no normalise/look)** with `--out`, `--json`. AC: end to end on the CC0 samples; originals untouched (hash check). T: integration test.
14. **Memory-capped worker pool**: `--workers`, `--memory-budget`; measure per-image peak. AC: never exceeds budget on a 33 MP file. T: slow test with RSS sampling.
15. **Memory/perf budget tests**: full-res Pocket 4 decode+export peak RAM and time recorded. AC: numbers in the project plan §5 updated with measured values. T: `pytest -m slow`.
16. **Comparison contact sheet** `scripts/compare.py`: ours vs in-camera JPEG (vs darktable render if present) per reference shot. AC: one PNG sheet. T: the user reviews; **this is the M1 acceptance gate**.
17. **`picturesq doctor`**: LibRaw version, supported cameras count, RAM, terminal graphics support. AC: `--json` output. T: snapshot test.
18. **Learning log + primer for M1**: demosaic, colour spaces/gamuts, display transforms, with a demo image (with/without AgX). T: user review + one quick check question.
