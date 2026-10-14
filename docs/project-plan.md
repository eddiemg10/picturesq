# picturesq — Project Plan

> Status: **M0 setup (draft for sign-off)** · Last updated: 2026-10-11
> The single source of truth for scope, decisions and milestones.
> Vocabulary: [`docs/glossary.md`](glossary.md) (binding). Decision rationale: [`docs/decisions/`](decisions/). Concepts: [`docs/learning-log.md`](learning-log.md). Tasks: [project board](https://github.com/users/eddiemg10/projects/1).

---

## 1. Vision

**picturesq turns a folder of RAW photos into consistently graded exports without ever opening a photo editor.**

You copy RAW originals into a project folder and run `picturesq run ./lisbon`. The tool decodes every photo, normalises exposure across photos and flags the ones it can't fix. You then open a tiny local web UI showing every photo × a grid of looks in four categories (B/W, Cold, Warm, Cinematic), pick looks, dive into one to set its intensity and parameters, and export. Every choice is saved to `picturesq.yaml`. A coding agent can also read and edit that file ("warmer shadows on the sunset photos"), and the same originals + config always give the same output.

### Product principles
1. **Never open a GUI editor.** The CLI + a minimal local web UI are the whole interface.
2. **Consistency through normalisation.** Photos are first brought to a common baseline; looks are graded on top and behave predictably.
3. **Light on resources.** It runs well on an 8 GB, CPU-only laptop. Interactive work uses proxies; full resolution only runs during export.
4. **Config is the product state.** Humans edit it through the web UI, agents through files/CLI. It is machine-owned YAML validated by a schema, and is never hand-edited by humans.
5. **Reproducible.** Deterministic pipeline; every export records the exact config + version used.
6. **Originals are sacred.** Never written.
7. **Well engineered.** Tested maths, CI on Linux + Windows, small reviewable PRs, documented decisions, open source from day one.

### Success criteria for v1 (v0.1.0)
- One command turns a project's originals into exports using looks chosen in the web UI.
- The neutral render looks at least as good as the camera's own JPEG on the reference set.
- A contact sheet of the normalised reference set looks even; outliers are flagged, not forced.
- An agent can make a described change ("softer highlights") by editing config, and the preview reflects it.
- 100 full-resolution Pocket 4 photos export in < 15 min on the reference laptop with peak RAM ≤ 3 GB.

### Non-goals (v1)
Photoshop-style GUI, local retouching, lens correction, cataloguing/DAM, ML training, GPU requirement, video.

---

## 2. Users and environments

| | |
|---|---|
| Primary user | Hobbyist photographer and software engineer; new to image science |
| Primary camera | DJI Osmo Pocket 4: DNG RAW (~33 MP, 7680×4320 at 16:9), 1-inch-class sensor, so noisy at night |
| Supported cameras | Anything LibRaw decodes (Canon, Nikon, Sony, Fuji, Panasonic, phone/drone DNG). New/unknown cameras: convert to DNG with Adobe DNG Converter. |
| Reference machine | WSL2 on Windows, 8 cores, 7.7 GB RAM, no usable GPU |
| Supported OS | Linux (incl. WSL2) and native Windows. macOS: best effort (not in CI for v1). |
| Python | ≥ 3.11 |
| Shooting mix | Daylight travel/street, low light/night, people/portraits, landscape/nature |
| Outputs | `web` (resized sRGB JPEG, e.g. 2048 px long edge) + `archive` (full-resolution JPEG) |

---

## 3. Key decisions (summary)

| # | Area | Decision | Why (short) |
|---|---|---|---|
| D1 | Language | Python | Fast to build/distribute; heavy lifting lives in C libraries (LibRaw, numpy). C++ buys speed we don't need given proxies. |
| D2 | Decoder | `rawpy` (LibRaw) only. [ADR-0001](decisions/0001-rawpy-decoder-no-darktable.md) | Light pip install, 1000+ cameras, embedded DNG matrices. darktable's XMP can't be generated from YAML, and its per-render process cost kills live previews. |
| D3 | Camera LUT | None; use the DNG colour matrices. [ADR-0002](decisions/0002-no-camera-conversion-lut.md) | DJI's D-Log LUTs are for D-Log *video*; DNG is linear sensor data. |
| D4 | Working space | Scene-linear float32, linear Rec.2020 primaries | Holds camera colours without clipping; linear makes exposure/WB physically correct. |
| D5 | Display transform | AgX-style. [ADR-0003](decisions/0003-agx-display-transform.md) | Graceful highlight roll-off, no hue skews; open design. |
| D6 | Normalise | Camera-fitted exposure offset (+2 EV); optional partial correction toward a target (off by default); chroma NR in the shadows; as-shot WB + disagreement flag (M2). [ADR-0010](decisions/0010-camera-matched-neutral-render.md) | Measured: cameras brighten by a near-constant amount, not per scene. Batch evening-out stays available. |
| D7 | Looks | Every look is a look file (YAML operations, optionally a `lut` operation); four categories | One concept; editable by agents; LUTs give breadth. |
| D8 | LUT maths | Our own numpy trilinear/tetrahedral; colour-science as **test oracle only** | ~30 lines, no heavy runtime dependency, verified against a reference. |
| D9 | Config | YAML, machine-owned, pydantic models = schema. [ADR-0004](decisions/0004-yaml-machine-owned.md) | Diffable and readable for agents; humans use the UI. |
| D10 | Previews | Terminal (sixel/kitty) view-only → `picturesq ui` | Quick glance in the terminal; real choices need accurate colour + controls. |
| D11 | UI stack | Starlette + htmx/vanilla JS, no build step. [ADR-0005](decisions/0005-web-ui-no-build.md) | Ships in the wheel; no Node toolchain. |
| D12 | Interactive rendering | Python renders an ~800–1200 px proxy per change | One implementation of the maths; ~50–150 ms. WebGL later if needed. |
| D13 | Storage | Proxies always cached; full-resolution 16-bit TIFF only with a flag | 16-bit TIFF is ~200 MB per photo; export re-decodes deterministically. |
| D14 | Distribution | **Public** GitHub repo from day one, MIT; PyPI via `uv tool install picturesq` | Build in public; free branch protection + CI; standard Python install path. |
| D15 | Process | GitHub Issues + Project board as the only tracker; PR-only changes, CI-gated | Treat it as a product; small tasks the user can pick up. |
| D16 | Vocabulary | [`glossary.md`](glossary.md) is binding; British spelling everywhere | Consistent, intentional language across code, CLI, config, docs and UI. |
| D17 | Neutral render acceptance | The real export against the camera JPEG: brightness, chroma per lightness band, clipping (`scripts/compare.py`). [ADR-0010](decisions/0010-camera-matched-neutral-render.md) (supersedes 0009) | Judging an exposure-matched image hid that real exports were 2 stops dark. |

---

## 4. The pipeline

```
 originals (read-only)
   │
   ▼
┌────────────┐  rawpy: unpack → black/white level → demosaic → as-shot WB → camera matrix
│ 1 DECODE   │  → scene-linear float32 in the working space               [camera-specific]
└─────┬──────┘  caches: proxy (2048 px, float16 .npy); optional full-res 16-bit TIFF
      ▼                                                                   [camera-agnostic ↓]
┌────────────┐  exposure (camera-fitted offset, optional partial correction) → chroma NR
│ 2 NORMALISE│  → stats → WB disagreement check → overrides → flags
└─────┬──────┘
      ▼
┌────────────┐  look operations (scene-linear, scaled by intensity) → adjustments
│ 3 GRADE    │  → display transform (AgX) → display-referred operations (e.g. lut)
└─────┬──────┘
      ▼
┌────────────┐  per output: resize → (display transform) → sRGB encode → sharpen → 8-bit JPEG + ICC + EXIF
│ 4 EXPORT   │  + sidecar (config snapshot, version, original hash)
└────────────┘
```
`picturesq preview` and `picturesq ui` run stages 2–3 on proxies; `picturesq export` runs 1–4 on originals.

### 4.1 Decode
- `rawpy.imread(...).postprocess(...)` with gamma 1, no auto-bright, 16-bit output, camera WB, **camera RGB** output; we apply the camera → Rec.2020 matrix ourselves in float32 so out-of-gamut colours survive (#47). Exact parameters (demosaic algorithm, highlight mode) are fixed in M1 with tests.
- **DNG lens corrections** (`OpcodeList3` gain maps and rectilinear warps), applied in camera RGB before the matrix. Implemented from the DNG spec, off by default until verified against a reference render (ADR-0010).
- **Proxy:** `half_size=True` skips demosaicing (≈4× fewer pixels, near-instant), then downscale to 2048 px long edge.
- The cache key is a hash of (original bytes, decode config, picturesq version), so a stale cache is impossible.

### 4.2 Normalise (algorithm v1)
Implemented (ADR-0010):
1. **Exposure:** `exposure_ev = offset_ev + clamp(correction × (target_ev − median_ev), ±max_correction_ev)`. `offset_ev` (+2.0) is fitted to camera JPEGs; `correction` defaults to 0 because cameras don't even out a batch. The median is measured on a ~100k-pixel grid.
2. **Chroma NR:** each pixel keeps its luminance and moves toward the local average chromaticity, smoothed on a small copy (radius a fraction of the long edge); full strength in the shadows, faded out 1.5 EV below mid grey.

Still to do (M2):
3. Stats per photo (p1/p5/p50/p95/p99, clipped fraction, mean chroma) written as JSON, plus a project summary; stats outside configured ranges mark the photo as an **outlier**.
4. **WB check:** grey-world/white-patch estimate vs as-shot; a difference > N mired raises flag `wb_disagreement` (no automatic change).
5. Overrides (`exposure_ev`, `wb_kelvin`, `tint`, `skip`) and flags (e.g. `exposure_clamped`).

Dropped after measurement (ADR-0010): key detection with per-key targets and the highlight guard (the camera-fitted curve keeps highlights below the white point; cameras don't normalise per scene). Local tone mapping is not planned: cameras showed no compression beyond their global curve.

### 4.3 Grade
- **Per photo:** one look + intensity + adjustments (project default, with optional per-photo override).
- **Look file:** metadata (name, category, description), **parameters** exposed to the UI, and an ordered list of **operations**.
- **Operations (v1):** scene-linear: `exposure`, `white_balance`, `contrast` (log-space pivot), `tone_curve`, `saturation`, `vibrance` (OkLCh chroma), `hsl` (hue bands), `split_tone`, `fade`, `channel_mixer` (B/W), `grain` (seeded), `vignette`. Display-referred (after AgX): `lut` (with a declared input space).
- **Intensity:** every operation parameter declares its neutral value; `effective = neutral + intensity × (value − neutral)`. For `lut`, intensity blends the LUT output with its input. 0 % = exactly the neutral render (tested); range 0–150 %.
- **Adjustments:** exposure, warmth, tint, contrast, saturation, vibrance. The same for every look, applied after the look's scene-linear operations.
- **Look library:** built-in looks at `picturesq/grade/looks/<category>/<name>.yaml` (3–4 per category in v1). User-installed looks and `.cube` files later (user look files are deferred; user `.cube` files are wrapped in a look file).

### 4.4 Export
- **Outputs** in config, e.g. `web: {long_edge: 2048, quality: 90}`, `archive: {long_edge: null, quality: 95}`; each has its own sharpening.
- sRGB ICC profile embedded; EXIF copied from the original where available.
- Sidecar `exports/<output>/<photo>.picturesq.json`: resolved config for that photo, picturesq version, original hash.

---

## 5. Resource model

| Item (33 MP Pocket 4 photo) | Size / cost |
|---|---|
| RAW in memory | ~66 MB (uint16 mosaic) |
| Full-resolution float32 RGB image | ~400 MB per array |
| Naive numpy operation chain | 1–2 GB peak (temporaries) |
| Full-resolution 16-bit TIFF on disk | ~200 MB |
| 2048 px float16 proxy on disk | ~14 MB |
| Demosaic (LibRaw, CPU) | ~2–6 s |
| Per-pixel operation at full resolution | ~0.5–3 s |
| Per-pixel operation on a 1000 px proxy | ~5–30 ms |

**Rules**
- Full-resolution stages operate in place where possible (`np.multiply(a, b, out=a)`), process neighbourhood operations in row tiles, and free arrays eagerly.
- Worker count = `min(cores, floor(memory_budget / per_photo_peak))`. The default budget of 2.5 GB gives ~2–3 workers on the reference laptop. `per_photo_peak` is measured by a test, not guessed.
- Interactive paths never touch full-resolution data.
- Budgets are enforced by tests (§8).

---

## 6. Config specification (draft; finalised in M1–M3)

YAML is written by the web UI and agents, never by hand. Pydantic models in `picturesq.config` are the source of truth; `picturesq schema` prints the JSON Schema.

### 6.1 Project config: `<project>/picturesq.yaml`
```yaml
version: 1
decode:
  demosaic: ahd                  # finalised in M1
  highlight_mode: blend
normalise:
  enabled: true
  exposure: {offset_ev: 2.0, correction: 0.0, target_ev: -1.0, max_correction_ev: 2.0}
  chroma_nr: {amount: 1.0, radius: 0.004, full_lightness: 0.2, fade_lightness: 0.4}
  white_balance: {mode: as_shot, flag_disagreement_mired: 30}   # M2
grade:
  look: {name: cold/nordic, intensity: 0.8, parameters: {}}
  adjustments: {exposure: 0.0, warmth: 0.0, tint: 0.0, contrast: 0.0, saturation: 0.0, vibrance: 0.0}
photos:                          # overrides, written by the UI
  DJI_20261011_0042.DNG:
    normalise: {exposure_ev: 0.3}
    grade:
      look: {name: bw/silver, intensity: 1.0}
export:
  outputs:
    web: {long_edge: 2048, quality: 90, sharpen: {amount: 0.5, radius: 0.8}}
    archive: {long_edge: null, quality: 95, sharpen: {amount: 0.3, radius: 1.2}}
  enabled: [web, archive]
```

### 6.2 Look file: `grade/looks/cold/nordic.yaml`
```yaml
version: 1
name: nordic
category: cold                   # bw | cold | warm | cinematic
description: Muted, cool shadows, clean whites, lifted blacks
parameters:                      # shown in the UI's look panel
  shadow_tint: {default: 0.10, min: 0, max: 0.3, label: Shadow tint}
  fade: {default: 0.05, min: 0, max: 0.2, label: Fade}
operations:
  - {op: white_balance, temperature: -400, tint: 0}
  - {op: contrast, amount: 0.15, pivot: 0.18}
  - {op: split_tone, shadows: {hue: 215, amount: $shadow_tint}, highlights: {hue: 45, amount: 0.03}}
  - {op: saturation, amount: -0.15}
  - {op: fade, amount: $fade}
```

---

## 7. CLI specification

| Command | Purpose |
|---|---|
| `picturesq run PROJECT` | Whole pipeline: decode → normalise → grade → export (creates `picturesq.yaml` with defaults if missing) |
| `picturesq decode PROJECT [--full-res]` | Decode originals, build proxies (+ optional 16-bit TIFFs) |
| `picturesq normalise PROJECT` | Compute stats, flags and normalisation; print a summary |
| `picturesq preview PROJECT [--category cold] [--png FILE]` | Contact sheet of photos × looks: in the terminal, or as a PNG |
| `picturesq looks [--category cold]` | List the look library |
| `picturesq ui PROJECT` | Start the local web UI (opens the browser) |
| `picturesq export PROJECT [--output web]` | Render originals and write enabled outputs |
| `picturesq schema [project\|look]` | Print the JSON Schema |
| `picturesq doctor` | Check environment: LibRaw version, terminal graphics, memory |

Global flags: `--out PATH` (redirect generated files), `--json` (machine-readable output), `--workers N`, `--memory-budget 2.5GB`, `-v/-q`.
Exit codes: 0 ok, 1 error, 2 invalid config/usage, 3 completed with flags (only with `--strict`).

### Project folder layout
```
lisbon/                    # a project
  DJI_….DNG                # originals, never written
  picturesq.yaml           # project config (UI/agents)
  .picturesq/              # cache: proxies/, decoded/, stats/, previews/
  exports/web/  exports/archive/
```

### Package layout (mirrors the pipeline)
```
src/picturesq/
  cli/         one module per command; --json rendering
  config/      pydantic models, YAML load/save (atomic), schema export
  colour/      shared maths: transfer functions, matrices, Oklab, AgX   (pure, no IO)
  decode/      stage 1: RAW discovery, rawpy decode, proxies
  normalise/   stage 2: stats, key, exposure, WB check, chroma NR, flags (pure)
  grade/       stage 3: operations, look files, intensity, adjustments, LUTs; looks/<category>/*.yaml
  export/      stage 4: JPEG/TIFF writers, ICC, EXIF, sidecar
  pipeline/    orchestration, cache, memory-capped workers
  preview/     contact sheets, terminal rendering
  ui/          Starlette app, templates, static
```
Rule: image operations are pure `f(image: float32 H×W×3, params) -> image`; only `decode`, `export`, `pipeline`, `preview`, `ui` and `config` touch files.

---

## 8. Quality and testing strategy

| Layer | What | How |
|---|---|---|
| Maths unit tests | transfer functions, matrices, Oklab, exposure, operations, LUT interpolation | pytest + hypothesis property tests (round-trips, identity, monotonicity, intensity 0 = neutral) |
| Oracle tests | colour maths against a reference | `colour-science` (dev dependency only) |
| Goldens | decode/normalise/grade on reference crops | ΔE2000 mean/p95 thresholds vs stored goldens; update with `scripts/update_goldens.py` (reviewed in PR) |
| Integration | real RAWs end-to-end | CC0 samples from raw.pixls.us, cached in CI; the reference set is private and runs locally only (`-m reference`, skipped when absent). Nothing derived from it (crops, goldens) is committed |
| Performance | per-operation timings, full pipeline | pytest-benchmark (local), smoke perf in CI |
| Memory | peak per photo at full resolution | RSS sampling; test fails above budget |
| CLI | `--json` output contracts, exit codes | snapshot tests |
| UI | grid loads, controls update preview, YAML written, agent edit live-reloads | Playwright e2e (smoke in CI, full locally) |
| Taste | does it look good? | contact sheets reviewed by the user at each milestone; that review is the acceptance gate |

**Every task's issue states how it is tested.** Maths without a test isn't merged.

---

## 9. Engineering workflow

- **Repo:** `github.com/eddiemg10/picturesq`, **public**, MIT.
- **Branching:** trunk-based. `main` is protected (PR required, CI must pass, linear history); short-lived branches `feat/…`, `fix/…`, `docs/…`, `chore/…`; squash-merge. Conventional-commit PR titles.
- **CI (GitHub Actions):** ruff (lint + format check), pyright, pytest on {ubuntu, windows} × {3.11, 3.13}, uv caching.
- **Release:** tag `vX.Y.Z` → build → PyPI via trusted publishing (enabled at M5; the name is claimed in M0).
- **Tooling:** uv, hatchling, ruff, pyright, pre-commit.
- **Tracking:** GitHub Project board is the **only** tracker (Backlog → Ready → In progress → Review → Done). Milestone per M-stage; issue template: context, acceptance criteria, test plan, learning note. Target size 30–60 min.
- **Who builds:** the user and agents (Claude Code via `@claude`, Codex cloud). Every implementer opens a PR; the user reviews and merges. Issues labelled `learn` are for the user to implement personally.
- **Agent context:** `AGENTS.md` + this doc + glossary + ADRs. Agents read these instead of re-exploring the repo.
- **Wireframes:** Figma (via the Figma MCP) for the UI in M4.
- **Public-repo hygiene:** no personal photos, paths or secrets committed; RAWs are git-ignored; goldens are small crops of CC0 samples only.

---

## 10. Milestones

Each milestone ends with a user review of a contact sheet/demo and one quick understanding check (teaching protocol).

### M0 — Setup (current)
Project plan, glossary, ADRs, learning log, scaffold, CI, public repo with protection, board + issues, connectors, reference set shot list, licence audit, PyPI name claimed.
**Exit:** CI green on both OSes; the user signs off this document; reference set shot.

### M1 — Decode & export (neutral render)
Decode via rawpy into the working space; proxies + cache; AgX display transform fitted to camera JPEGs; exposure offset and chroma NR (pulled forward from M2, ADR-0010); output sharpening; sRGB JPEG export with ICC/EXIF; `decode`, `export`, `run`; `scripts/compare.py` contact sheet and gate: ours vs in-camera JPEG.
**Concepts:** RAW/demosaic, linear vs display-referred, colour spaces and gamuts, display transforms.
**Exit:** `scripts/compare.py` passes its gate on the CC0 samples and on the reference set (real export vs camera JPEG: median |ΔEV| ≤ 0.5, chroma per lightness band within 0.8–1.25, no extra clipping; [ADR-0010](decisions/0010-camera-matched-neutral-render.md)), the user judges the sheet comparable or better; memory budget test passes.

### M2 — Normalise
Stats JSON, WB disagreement flag, overrides, flags, outliers, `normalise` command + contact sheet (exposure and chroma NR landed in M1, ADR-0010).
**Concepts:** EV/stops and histograms, white balance (temperature/tint, mired), noise.
**Exit:** outliers are flagged, not forced; with `correction` on, the reference-set contact sheet looks even.

### M3 — Grade: look engine, look library, previews
Operations, look file schema + intensity, `lut` operation (oracle-tested), adjustments, 12–16 built-in looks, `preview` and `looks` commands (output sharpening landed in M1).
**Concepts:** tone curves, Oklab/OkLCh, what a `.cube` LUT is, split toning, unsharp mask.
**Exit:** an agent makes a described change via config and the preview reflects it.

### M4 — UI
Starlette app, photo × look grid, look panel (intensity / parameters / adjustments), per-photo normalisation review, YAML write-back, file watching, Playwright tests.
**Exit:** the user grades a whole project without touching YAML; an agent edit live-reloads in the browser.

### M5 — v0.1 release
Performance pass (100 photos < 15 min), README/docs, Claude skill, PyPI release.
**Exit:** `uv tool install picturesq` works on a clean Windows and Linux machine.

### Later (out of scope for v1)
Inspiration-image → draft look; sky segmentation (SegFormer, ADE20K) + sky-only grading; skin/foliage/water regions; luma NR; user look files saved from the UI; MCP server; WebGL previews; per-camera presets; metadata editing; macOS CI.

---

## 11. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Neutral render worse than the camera JPEG (camera JPEGs include lens/noise processing) | Users bounce | M1 acceptance compares directly; tune AgX + chroma NR; luma NR moves up if needed |
| Pocket 4 DNG oddities (linear vs mosaic DNG, opcodes LibRaw ignores, lens tags) | Colour/geometry off | Inspect reference DNGs in M0; document findings |
| Night photos too noisy without luma NR | Bad night results | Measure on the reference set in M2; escalate the luma NR decision |
| Memory blow-ups at 33 MP | Crashes on 8 GB | In-place operations, tiling, budget tests from M1 |
| Look quality is subjective | Endless tuning | Small library, user review gates, agent-assisted iteration |
| LUT/AgX licensing | Can't ship assets | Licence audit in M0; implement AgX from the published maths |
| UI scope creep | Delays v1 | v1 UI scope frozen (M4); everything else is backlog |
| YAML races (UI and agent editing at once) | Lost edits | Atomic writes + reload on change; last write wins, with a UI notice |
| Public repo leaks personal data | Privacy | Git-ignored RAWs; goldens from CC0 samples only; pre-commit large-file check |

---

## 12. Dependencies (proposed; additions need approval)

| Runtime | Purpose | Added in |
|---|---|---|
| typer | CLI | M0 |
| rawpy | RAW decode (LibRaw) | M1 |
| numpy | maths | M1 |
| pydantic | config models + schema | M1 |
| pyyaml | YAML I/O | M1 |
| pillow | JPEG export, ICC profile, resize | M1 |
| tifffile | 16-bit TIFF | M1 |
| starlette + uvicorn | UI | M4 |
| watchfiles | config live reload | M4 |
| *(decide in M1)* opencv-python-headless | fast blur/resize, only if Pillow/numpy is too slow | — |

Dev: pytest, hypothesis, pytest-benchmark, colour-science (oracle), ruff, pyright, pre-commit, playwright (M4).

What each dependency is for: [`docs/dependencies.md`](dependencies.md).

---

## 13. Agent integration

- **CLI contract:** every command supports `--json`; errors are structured; the schema is printable.
- **Visual feedback for agents:** `picturesq preview PROJECT --png sheet.png` writes a contact sheet an agent can view.
- **Skill:** `skills/picturesq/SKILL.md` teaches agents the workflow and how words map to config ("warmer shadows" → `split_tone.shadows`, "softer highlights" → display transform/contrast parameters).
- **Connectors:** [`docs/setup-connectors.md`](setup-connectors.md).

---

## 14. Open questions
1. Can the Pocket 4 shoot DNG + JPEG simultaneously? (Useful for the M1 comparison.) **Deferred (#5): not checked. The M1 comparison uses the embedded 720×1280 JPEG preview in each DNG as the in-camera reference, for simplicity.**
2. Are Pocket 4 DNGs mosaic (Bayer) or linear (demosaiced)? This determines whether demosaic settings matter. **Answered (#4): mosaic (Bayer `R G / G B`), so demosaic settings matter.** See the learning log (2026-10-12) for the rest of the DNG structure.
3. Licences: AgX reference implementations, RawTherapee film-simulation Hald CLUTs (per-collection terms). **Answered (#7, [ADR 0007](decisions/0007-asset-licences.md)):** port the AgX maths from published sources only (no GPL code, no verbatim Blender/darktable files); the film-simulation collection (CC BY-SA 4.0 overall, `CreativePack-1` unclear) is not bundled by default, optional download only.
