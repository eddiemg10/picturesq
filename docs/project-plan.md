# picturesq — Project Plan

> Status: **Phase 0 complete (draft for sign-off)** · Last updated: 2026-10-11
> This document is the single source of truth for scope, decisions and milestones.
> Short decision records with rationale live in [`docs/decisions/`](decisions/).
> Concepts are explained in [`docs/learning-log.md`](learning-log.md).

---

## 1. Vision

**picturesq turns a folder of RAW photos into consistently edited, good-looking exports without ever opening a photo editor.**

You copy a trip's RAWs into a folder and run `picturesq run ./trip`. The tool develops every photo to a neutral baseline, evens out exposure across shots and flags the ones it can't fix. You then open a tiny local web page showing every photo × a grid of looks (B/W, Cold, Warm, Cinematic), pick looks, dive into one to tune intensity, and export. Every choice is saved to a YAML file. A coding agent can also read and edit that file ("warmer shadows on the sunset shots"), and the same input + config always gives the same output.

### Product principles
1. **Never open a GUI editor.** The CLI + a minimal local web page are the whole interface.
2. **Consistency through normalisation.** Photos are first brought to a common baseline; looks are applied on top and behave predictably.
3. **Light on resources.** It runs well on an 8 GB, CPU-only laptop. Interactive work happens on small proxies; full-res only runs in batch.
4. **Config is the product state.** Humans edit it through the web UI, agents through files/CLI. It is machine-owned YAML validated by a schema, and is never hand-edited by humans.
5. **Reproducible.** Deterministic pipeline; every export records the exact config + version used.
6. **Originals are sacred.** Input files are never written.
7. **Well engineered.** Tested maths, CI on Linux + Windows, small reviewable PRs, documented decisions.

### Success criteria for v1 (v0.1.0)
- One command converts a folder of RAWs into exports using looks chosen in the web UI.
- The neutral render looks at least as good as the camera's own JPEG on the reference set.
- A contact sheet of normalised reference shots looks even; outliers are flagged, not forced.
- An agent can make a described change ("softer highlights") by editing config, and the preview reflects it.
- 100 full-res Pocket 4 photos export in < 15 min on the reference laptop with peak RAM ≤ 3 GB.

### Non-goals (v1)
Photoshop-style GUI, local retouching, lens correction, cataloguing/DAM, ML training, GPU requirement, video.

---

## 2. Users and environments

| | |
|---|---|
| Primary user | Hobbyist photographer and software engineer; new to image science |
| Primary camera | DJI Osmo Pocket 4: DNG RAW stills (~33 MP, 7680×4320 at 16:9), 1-inch-class sensor, so noisy at night |
| Supported cameras | Anything LibRaw decodes (Canon, Nikon, Sony, Fuji, Panasonic, phone/drone DNG). Unknown or new cameras: convert to DNG with Adobe DNG Converter. |
| Reference machine | WSL2 on Windows, 8 cores, 7.7 GB RAM, no usable GPU |
| Supported OS | Linux (incl. WSL2) and native Windows. macOS: best effort (not in CI for v1). |
| Python | ≥ 3.11 |
| Shooting mix | Daylight travel/street, low light/night, people/portraits, landscape/nature |
| Output | Social/web (resized sRGB JPEG, e.g. 2048 px long edge) + full-res archive JPEG |

---

## 3. Key decisions (summary)

Each row links to an ADR when the reasoning is non-trivial.

| # | Area | Decision | Why (short) |
|---|---|---|---|
| D1 | Language | Python | Fast to build/distribute; heavy lifting lives in C libraries (LibRaw, numpy). C++ buys speed we don't need given the proxy strategy. |
| D2 | Decoder | `rawpy` (LibRaw) only. [ADR-0001](decisions/0001-rawpy-decoder-no-darktable.md) | Light pip install, 1000+ cameras, embedded DNG matrices. darktable's XMP format can't be generated from YAML, and its per-render process cost kills live previews. |
| D3 | Camera LUT | None. Use the DNG colour matrices. [ADR-0002](decisions/0002-no-camera-conversion-lut.md) | DJI's D-Log LUTs are for *video* in D-Log encoding; DNG is linear sensor data. Applying them would be a colour-space mismatch. |
| D4 | Working space | Scene-linear float32, **linear Rec.2020 primaries** | Wide enough to hold camera colours without clipping; linear makes exposure/WB physically correct. |
| D5 | Display transform | AgX-style transform as the neutral base. [ADR-0003](decisions/0003-agx-display-transform.md) | Graceful highlight roll-off and no hue skews (the "Notorious 6"); open design. |
| D6 | Normalisation | Key-aware partial auto-exposure, as-shot WB + disagreement flag, chroma NR | Keeps night shots moody, fixes errors, flags what it can't fix. |
| D7 | Looks | Parametric recipes (scene-side) + user `.cube` LUTs (display-side); 4 categories | Recipes are editable by agents and explainable; LUTs give breadth. |
| D8 | LUT maths | Our own numpy trilinear/tetrahedral; colour-science as **test oracle only** | ~30 lines, no heavy runtime dep, verified against a reference implementation. |
| D9 | Config | YAML, machine-owned, pydantic models = schema. [ADR-0004](decisions/0004-yaml-machine-owned.md) | Readable + diffable for agents/reproducibility; humans edit via the UI only. |
| D10 | Preview | Terminal (sixel/kitty) view-only → `picturesq ui` localhost editor | Quick glance in the terminal; real editing needs colour-accurate pixels + sliders. |
| D11 | Web stack | Starlette + htmx/vanilla JS, no build step. [ADR-0005](decisions/0005-web-ui-no-build.md) | Ships inside the wheel; no Node toolchain; enough for a grid + sliders. |
| D12 | Slider rendering | Python re-renders an ~800–1200 px proxy per change | One implementation of the maths; ~50–150 ms latency. WebGL is a later optimisation. |
| D13 | Storage | Cache proxies always; full-res TIFF intermediates only with a flag | 16-bit full-res TIFF is ~200 MB per photo; export re-decodes deterministically. |
| D14 | Distribution | PyPI, `uv tool install picturesq`; private repo until v0.1, then public, MIT | Standard Python path; wheels exist for rawpy/numpy on Linux + Windows. |
| D15 | Process | GitHub Issues + Project board, PR-only changes, CI-gated | Treat it like a product; small tasks the user can pick up. |

---

## 4. The pipeline

```
 RAW files (read-only)
   │
   ▼
┌───────────┐  rawpy: unpack → black/white level → demosaic → as-shot WB → camera matrix
│ 1 DEVELOP │  output: scene-linear float32, linear Rec.2020           [camera-specific]
└─────┬─────┘  caches: proxy (2048 px, float16 .npy) + optional full-res 16-bit TIFF
      ▼                                                               [camera-agnostic ↓]
┌─────────────┐ stats → key detection → exposure gain (partial, clamped) → highlight guard
│ 2 NORMALISE │ → WB disagreement check → chroma NR → per-photo overrides
└─────┬───────┘ output: normalised scene-linear + stats.json + flags
      ▼
┌───────────┐  scene-side: parametric look recipe (strength-scaled) + fine-tune layer
│ 3 LOOK    │  display transform (AgX) → display-side: optional .cube LUT (blend)
└─────┬─────┘  → sharpen (output-size aware)
      ▼
┌───────────┐  sRGB encode, resize per output profile, 8-bit JPEG + ICC + EXIF,
│ 4 EXPORT  │  sidecar: config snapshot + tool version + input hash
└───────────┘
```

### 4.1 Develop
- `rawpy.imread(...).postprocess(output_color=..., gamma=(1,1), no_auto_bright=True, output_bps=16, use_camera_wb=True)`, converted to float32. Exact parameters (output space, demosaic algorithm, highlight mode) are fixed in M1 with tests.
- **Proxy mode:** `half_size=True` skips demosaicing (≈4× fewer pixels, near-instant), then downscale to 2048 px long edge. Interactive features only ever use proxies.
- The cache key is a hash of (file bytes, develop config, tool version), so a stale cache is impossible.

### 4.2 Normalise (algorithm v1)
1. Compute luminance Y (linear) on the proxy, then stats: percentiles p1/p5/p50/p95/p99, clipped fraction, mean chroma.
2. **Key detection** from the histogram shape (thresholds in config): low-key (night/moody), normal, high-key (snow/beach).
3. Target median per key (e.g. 0.06 / 0.18 / 0.35, tunable). `gain_ev = log2(target / median)`.
4. **Partial correction:** `applied_ev = clamp(correction_strength × gain_ev, ±max_ev)` (default 0.6, 2 EV).
5. **Highlight guard:** if after gain more than `max_clip_fraction` of pixels exceeds the display transform's white point, lower the gain.
6. **WB check:** run a gray-world/white-patch estimator. If it disagrees with as-shot by more than N mired, flag it (no auto-change).
7. **Chroma NR:** convert to an opponent/Oklab-like space, blur only chroma with a radius scaled by ISO, convert back.
8. Apply per-photo overrides (`exposure_ev`, `wb_kelvin`, `tint`, `skip_normalise`).
9. Emit `stats.json` per photo + a batch summary; mark outliers whose stats fall outside configured ranges or where the clamp was hit.

### 4.3 Look
- **Look = one base recipe + intensity + fine-tune layer.**
- **Parametric recipe ops** (scene-side, in linear or Oklab/OkLCh): exposure offset, contrast around mid-grey (log-space pivot), tone curve, white balance shift (temperature/tint), saturation and vibrance (OkLCh chroma), HSL-band adjustments, split toning (shadow/highlight hue + strength), fade (lifted blacks), B/W channel mixer, grain (luminance-dependent, seeded for determinism), vignette.
- **Intensity semantics:** each recipe op declares its neutral value; `effective = neutral + intensity × (param − neutral)`. Intensity 0 is exactly the neutral render (tested). Range 0–150%.
- **User `.cube` LUTs:** loaded from `~/.config/picturesq/luts/` or the project; each has metadata (category, input space: `srgb` | `rec709` | `log-…`). Applied after the display transform. Intensity = blend with the pre-LUT image.
- **Fine-tune layer (universal tweaks):** exposure, warmth, tint, contrast, saturation, vibrance. Same knobs for every look.
- **Sharpening:** unsharp mask at output resolution, so web and full-res get different radii.
- **Library:** `looks/builtin/<category>/<name>.yaml`, 3–4 per category in v1. User looks are deferred.

### 4.4 Export
- Output profiles in config, e.g. `web: {long_edge: 2048, quality: 90}` and `archive: {long_edge: null, quality: 95}`.
- sRGB ICC embedded; EXIF copied from the RAW (capture time, camera, lens) where available.
- Sidecar `exports/<name>.picturesq.json`: resolved config for that photo, tool version, input file hash.

---

## 5. Resource model

| Item (33 MP Pocket 4) | Size / cost |
|---|---|
| RAW in memory | ~66 MB (uint16 mosaic) |
| Full-res float32 RGB | ~400 MB per array |
| Naive numpy op chain | 1–2 GB peak (temporaries) |
| Full-res 16-bit TIFF on disk | ~200 MB |
| 2048 px float16 proxy on disk | ~14 MB |
| Demosaic (LibRaw, CPU) | ~2–6 s |
| Per-pixel op at full res | ~0.5–3 s |
| Per-pixel op on 1000 px proxy | ~5–30 ms |

**Rules**
- Full-res stages operate in place where possible (`np.multiply(a, b, out=a)`), process in **row tiles** for neighbourhood ops, and free arrays eagerly.
- Batch parallelism = `min(cores, floor(memory_budget / per_image_peak))`. The default budget of 2.5 GB gives ~2–3 workers on the reference laptop. `per_image_peak` is measured by a test, not guessed.
- Interactive paths never touch full-res data.
- Budgets are enforced by tests (§8).

---

## 6. Config specification (draft; finalised in M1–M3)

YAML is written by the web UI and agents, never by hand. Pydantic models in `picturesq.config` are the source of truth; `picturesq schema` prints the JSON Schema.

### 6.1 Project file: `trip/picturesq.yaml`
```yaml
version: 1
develop:
  demosaic: ahd              # finalised in M1
  highlight_mode: blend
normalise:
  enabled: true
  correction_strength: 0.6
  max_ev: 2.0
  targets: {low_key: 0.06, normal: 0.18, high_key: 0.35}
  max_clip_fraction: 0.002
  white_balance: {mode: as_shot, flag_disagreement_mired: 30}
  chroma_nr: {enabled: true, strength: auto}
look:
  default: {name: cold/nordic, intensity: 0.8}
  tweaks: {exposure: 0.0, warmth: 0.0, tint: 0.0, contrast: 0.0, saturation: 0.0, vibrance: 0.0}
photos:                       # per-photo overrides (written by the UI)
  DJI_20261011_0042.DNG:
    normalise: {exposure_ev: 0.3}
    look: {name: bw/silver, intensity: 1.0}
export:
  profiles:
    web: {long_edge: 2048, quality: 90, sharpen: {amount: 0.5, radius: 0.8}}
    archive: {long_edge: null, quality: 95, sharpen: {amount: 0.3, radius: 1.2}}
  enabled: [web, archive]
```

### 6.2 Look recipe: `looks/builtin/cold/nordic.yaml`
```yaml
version: 1
name: nordic
category: cold                 # bw | cold | warm | cinematic
description: Muted, cool shadows, clean whites, lifted blacks
params:                        # exposed in the dive-in panel
  shadow_tint: {default: 0.10, min: 0, max: 0.3, label: Shadow tint}
  fade: {default: 0.05, min: 0, max: 0.2, label: Fade}
ops:
  - {op: white_balance, temperature: -400, tint: 0}
  - {op: contrast, amount: 0.15, pivot: 0.18}
  - {op: split_tone, shadows: {hue: 215, strength: $shadow_tint}, highlights: {hue: 45, strength: 0.03}}
  - {op: saturation, amount: -0.15}
  - {op: fade, amount: $fade}
```

---

## 7. CLI specification

| Command | Purpose |
|---|---|
| `picturesq run DIR` | Develop → normalise → look → export using `DIR/picturesq.yaml` (created with defaults if missing) |
| `picturesq develop DIR [--full-res]` | Decode RAWs, build proxies (+ optional 16-bit TIFFs) |
| `picturesq normalise DIR` | Compute stats, flags, normalisation; print a summary |
| `picturesq looks DIR [--category cold] [--web]` | Render photo × look contact sheet: terminal view, PNG file, or open the web UI |
| `picturesq ui DIR` | Start the localhost editor (opens the browser) |
| `picturesq export DIR [--profile web]` | Full-res render and export |
| `picturesq schema [project|look]` | Print the JSON Schema |
| `picturesq doctor` | Check environment: rawpy/LibRaw version, terminal graphics support, memory |

Global flags: `--out PATH` (redirect outputs), `--json` (machine-readable output), `--workers N`, `--memory-budget 2.5GB`, `-v/-q`.
Exit codes: 0 ok, 1 error, 2 invalid config/usage, 3 completed with flagged outliers (only with `--strict`).

### Project folder layout
```
trip/
  DJI_….DNG               # originals, never written
  picturesq.yaml          # state (UI/agents)
  .picturesq/             # cache: proxies/, developed/, stats/, renders/
  exports/web/  exports/archive/
```

---

## 8. Quality and testing strategy

| Layer | What | How |
|---|---|---|
| Maths unit tests | transfer functions, matrices, Oklab, exposure, curves, LUT interpolation | pytest + hypothesis property tests (round-trips, identity, monotonicity, intensity 0 = identity) |
| Oracle tests | colour maths against a reference | `colour-science` (dev dependency only) |
| Golden images | develop/normalise/look on reference crops | ΔE2000 mean/p95 thresholds vs stored goldens; update with `scripts/update_goldens.py` (reviewed in PR) |
| Integration | real RAWs end-to-end | small CC0 samples from raw.pixls.us, cached in CI; Pocket 4 set runs locally (too large and personal to commit) |
| Performance | per-op timings, full pipeline | pytest-benchmark (local, tracked), smoke perf in CI |
| Memory | peak per image at full res | tracemalloc / RSS sampling; test fails above budget |
| CLI | `--json` output contracts, exit codes | snapshot tests |
| Web UI | grid loads, slider updates preview, YAML written, agent edit live-reloads | Playwright e2e (smoke in CI, full suite local) |
| Taste | does it look good? | contact sheets reviewed by the user at each milestone; that review is the acceptance gate |

**Every task's issue states how it is tested.** Maths without a test isn't merged.

---

## 9. Engineering workflow

- **Repo:** `github.com/eddiemg10/picturesq`, private until v0.1, then public (MIT).
- **Branching:** trunk-based. `main` is always green; short-lived branches `feat/…`, `fix/…`, `docs/…`; squash-merge PRs. Conventional-commit style titles.
- **Branch protection:** not available for private repos on GitHub Free, so rely on discipline (PR-only) until public, then enable required checks.
- **CI (GitHub Actions):** ruff (lint + format check), pyright, pytest on {ubuntu, windows} × {3.11, 3.13}. uv caching.
- **Release:** tag `vX.Y.Z` → build wheel/sdist → PyPI via trusted publishing (enabled at M5).
- **Tooling:** uv (envs, lock, run), hatchling build, ruff, pyright, pre-commit.
- **Task tracking:** GitHub Project board (Backlog → Ready → In progress → Review → Done). Milestone per phase. Issue template: context, acceptance criteria, test plan, learning note. Target size 30–60 min.
- **Who builds:** the user and agents (Claude Code via `@claude`, Codex cloud). Any implementer opens a PR; the user reviews and merges. Some tasks are labelled `learn` for the user to implement personally.
- **Agent context:** `AGENTS.md` (root) + this doc + ADRs. Agents don't re-explore the repo; they read these first.
- **Wireframes:** Figma (via the Figma MCP) for the web UI in M4, with ASCII wireframes in the issue as a fallback.

---

## 10. Milestones

Each milestone ends with a user review of a contact sheet / demo and one quick understanding check (teaching protocol).

### M0 — Setup (this phase)
Project plan, ADRs, learning log, scaffold, CI, GitHub board + issues, connectors guide, reference shot list, licence audit, PyPI name claim.
**Exit:** CI green on both OSes; the user signs off this document; reference set shot.

### M1 — Develop & export (neutral render)
Decode via rawpy into linear Rec.2020; proxies + cache; AgX display transform; sRGB JPEG export with ICC/EXIF; `develop`, `export`, `run` (no normalise/look); contact sheet `scripts/compare.py` showing ours vs in-camera JPEG vs darktable default.
**Concepts:** RAW/demosaic, linear vs display encoding, colour spaces and gamuts, display transforms.
**Exit:** on the reference set, the neutral render is judged at least as good as the in-camera JPEG; memory budget test passes.

### M2 — Normalise
Stats, key detection, partial exposure, highlight guard, WB disagreement flag, chroma NR, overrides, stats.json, outlier summary, `normalise` command + contact sheet.
**Concepts:** stops/EV and histograms, white balance (temperature/tint, mired), noise.
**Exit:** the contact sheet looks even across easy/hard shots; outliers flagged, not forced.

### M3 — Look engine + library + terminal previews
Op library, recipe schema + intensity semantics, `.cube` loading/application (oracle-tested), fine-tune layer, 12–16 built-in looks, sharpening, `looks` command with terminal + PNG contact sheets.
**Concepts:** tone curves, Oklab/OkLCh, what a `.cube` LUT is, split toning, unsharp mask.
**Exit:** an agent makes a described change via config and the preview reflects it.

### M4 — Web UI
Starlette app, photo × look grid, dive-in panel (intensity / look params / universal tweaks), per-photo normalisation review, YAML write-back, file watching, Playwright tests.
**Exit:** the user tunes a whole trip without touching YAML, and an agent edit live-reloads in the browser.

### M5 — v0.1 release
Perf pass to hit the 100-photo / 15-min target, docs/README, Claude skill + AGENTS snippet, go public, PyPI release.
**Exit:** `uv tool install picturesq` works on a clean Windows and Linux machine.

### Later (Phase 4+, out of scope)
Inspiration-image → draft look; sky segmentation (SegFormer, ADE20K) + sky-only grades; skin/foliage/water regions; luma NR; saved user looks; MCP server; WebGL previews; per-camera presets; metadata editing; macOS CI.

---

## 11. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Neutral render worse than the camera JPEG (camera JPEGs include lens/noise processing) | Users bounce | M1 acceptance compares directly; tune AgX + chroma NR; luma NR moves up if needed |
| Pocket 4 DNG oddities (linear vs mosaic DNG, embedded lens corrections, opcodes LibRaw ignores) | Colour/geometry off | Inspect reference DNGs early (M0/M1 task); document findings |
| Night shots too noisy without luma NR | Bad night results | Measure on the reference set in M2; escalate the luma NR decision |
| Memory blow-ups at 33 MP | Crashes on 8 GB | In-place ops, tiling, budget tests from M1 |
| Look quality is subjective | Endless tuning | Small library, user review gates, agent-assisted iteration |
| LUT/AgX licensing | Can't ship assets | Licence audit in M0; implement AgX from the published maths ourselves |
| Web UI scope creep | Delays v1 | v1 UI scope frozen (§4.3, M4); everything else is backlog |
| YAML races (UI and agent editing at once) | Lost edits | Atomic writes + version field + reload-on-change; last-write-wins with a UI warning |

---

## 12. Dependencies (proposed; additions need approval)

| Runtime | Purpose |
|---|---|
| rawpy | RAW decode (LibRaw) |
| numpy | maths |
| pydantic | config models + schema |
| pyyaml | YAML I/O |
| typer | CLI |
| pillow | JPEG export, ICC, resize |
| tifffile | 16-bit TIFF |
| starlette + uvicorn | web UI (M4) |
| watchfiles | config live reload (M4) |
| *(decide in M1)* opencv-python-headless | fast blur/resize; only if Pillow/numpy is too slow |

Dev: pytest, hypothesis, pytest-benchmark, colour-science (oracle), ruff, pyright, pre-commit, playwright (M4).

---

## 13. Agent integration

- **CLI contract:** every command supports `--json`; errors are structured; the schema is printable.
- **Visual feedback for agents:** `picturesq looks DIR --png out.png` writes a contact sheet an agent can view.
- **Skill:** `skills/picturesq/SKILL.md` teaches agents the workflow and the mapping from words to config ("warmer shadows" → `split_tone.shadows.hue/strength`, "softer highlights" → AgX/contrast params).
- **Connectors:** see [`docs/setup-connectors.md`](setup-connectors.md).

---

## 14. Open questions
1. Can the Pocket 4 shoot DNG + JPEG simultaneously? (Useful for M1 comparison.)
2. Are Pocket 4 DNGs mosaic (Bayer) or linear (demosaiced) DNG? Determines whether demosaic settings matter.
3. Licences: AgX reference implementations, RawTherapee film-simulation HaldCLUTs (per-pack terms).
4. Final licence choice (MIT proposed).
