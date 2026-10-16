# Glossary

**The single source of vocabulary for picturesq.** Code, CLI, config keys, docs, issues and UI labels use these words and only these words. If you need a new term, add it here in the same PR.

## Language rules
- **British spelling everywhere**: *colour, normalise, grey, behaviour, licence* (noun) / *license* (verb). This applies to identifiers too: `colour/`, `normalise()`, `grey_point`.
  Exceptions: third-party APIs we call (`rawpy ... output_color`), CSS properties, and quoted product names.
- Config keys and identifiers are `snake_case`; CLI flags are `--kebab-case`.
- Prefer the industry term when one exists (sources: ACES/OpenColorIO, darktable, Lightroom, Capture One).

## Things
| Term | Meaning | Not to be called |
|---|---|---|
| **project** | A folder of RAW files plus its `picturesq.yaml`. The unit every command works on. | trip, batch, session, album |
| **photo** | One input RAW file and everything derived from it. Used in the UI, CLI output and config (`photos:`). | image (in user-facing text), shot, frame, picture |
| **image** | An in-memory pixel array (code only): `image: NDArray[float32]` of shape H×W×3. | photo (in code) |
| **original** | The RAW file on disk. Never written. | source, input file |
| **proxy** | A small cached scene-linear version of a photo (2048 px, float16) used for all interactive work. | thumbnail, preview (that's the rendered result) |
| **preview** | A display-ready render of a proxy, shown in the terminal or UI. | proxy, thumbnail |
| **contact sheet** | A grid of previews (photos × looks, or photos only). | gallery, mosaic |
| **stage sheet** | A contact sheet of one CC0 sample after each pipeline stage, beside the camera JPEG; shown in PR descriptions. | PR preview, screenshot |
| **look** | A named, reusable creative grade, e.g. *cold/nordic*. Defined by a **look file**. | style, preset, filter, recipe, profile |
| **look file** | YAML defining a look: metadata, **parameters**, and a list of **operations**, which may include a `lut` operation referencing a `.cube`. | recipe |
| **category** | A grouping of looks: `bw`, `cold`, `warm`, `cinematic`. | family, collection, group |
| **look library** | All available looks: built-in + user-installed. | catalogue, pack |
| **LUT** | A 3D lookup table file (`.cube`). Always used *through* a look file that declares its **input space**. | filter, profile |
| **Hald CLUT** | A **LUT** stored as a square image (PNG/TIFF) instead of a `.cube`; used by RawTherapee's Film Simulation Collection. Only ever a source format: convert to `.cube` before use, and keep the collection's licence and attribution with it. | HaldCLUT, preset image |
| **operation (op)** | One step inside a look file, e.g. `contrast`, `split_tone`, `lut`. | module, node, tool, effect |
| **parameter** | A named, adjustable value a look exposes to the UI (e.g. *shadow tint*). | knob, setting, control |
| **intensity** | How strongly a look applies: 0 % = neutral render, 100 % = as designed, up to 150 %. The only word for this. | strength, amount, opacity, mix |
| **amount** | The magnitude parameter *inside* an operation (`contrast.amount`). Never used for looks. | strength |
| **adjustments** | The fixed set of global controls available for every look: exposure, warmth, tint, contrast, saturation, vibrance. | tweaks, fine-tune layer, basics |
| **override** | A per-photo value that replaces the project default (look, intensity, normalisation values). | exception, manual edit |
| **output** | A named export target in config, e.g. `web`, `archive` (size, quality, sharpening). | export profile, preset, recipe |
| **ICC profile** | The colour profile embedded in an exported file. The only use of "profile". | — |
| **stats** | Per-photo measurements (luminance percentiles, clipping, …), stored as JSON. | metrics, analysis |
| **flag** | A per-photo warning raised by a stage (e.g. `exposure_clamped`, `wb_disagreement`). | warning, alert, issue |
| **outlier** | A photo whose stats fall outside configured ranges; one kind of flag. | — |
| **reference set** | The user's local Pocket 4 RAWs (scenarios R01–R10) used for acceptance. | test images |
| **stand-in** | A reference set photo covering a scenario until a proper shot exists (`status: stand-in` in the manifest). | placeholder, substitute |
| **samples** | CC0 RAWs from raw.pixls.us used in CI. | fixtures (fixture = pytest) |
| **camera JPEG** | The JPEG the camera embedded in the original: the reference our neutral render is compared against (`scripts/compare.py`). Some cameras embed a neighbouring frame; those are left out. | in-camera JPEG, preview |
| **golden** | A stored expected output used by a regression test. | snapshot (that's for text/JSON) |

## Pipeline
| Term | Meaning | Not to be called |
|---|---|---|
| **pipeline** | The full chain: decode → normalise → grade → export. | workflow, process |
| **stage** | One of the four pipeline steps below. | phase (that's project management), step |
| **decode** | Stage 1: original → scene-linear image in the working space (rawpy/LibRaw), plus proxy. | develop, import, convert, ingest |
| **normalise** | Stage 2: adaptive per-photo correction to a common baseline (exposure, WB check, chroma NR). | auto, correct, balance |
| **grade** | Stage 3: apply the photo's look + adjustments, then the display transform. The *act*; a look is the *thing*. | style, edit, look (as a verb) |
| **export** | Stage 4: encode, resize and write each enabled output with sidecar. | render, save |
| **render** | Producing pixels from a proxy or original through stages 2–3 (used by preview and export). | process |

## Colour science
| Term | Meaning |
|---|---|
| **scene-linear** | Pixel values proportional to light in the scene. All maths before the display transform happens here. |
| **working space** | The colour space of scene-linear images inside picturesq: linear Rec.2020 primaries, float32. |
| **primaries** | The exact red, green and blue a colour space's channels mean, given as xy chromaticities. |
| **white point** | The colour of R = G = B in a space. Ours is always D65 (daylight, xy 0.3127, 0.3290). |
| **gamut** | The range of colours a space can represent: the triangle its primaries span. Rec.2020's contains Rec.709/sRGB's. |
| **out-of-gamut** | A colour the target space can't represent; after a matrix conversion it has a negative channel. |
| **XYZ** | CIE 1931 XYZ, the device-independent reference space every RGB space is defined against. Y is luminance. |
| **display transform** | Maps scene-linear to display range with highlight roll-off. Ours is AgX-style. (OCIO: *view transform*; ACES: *output transform*.) |
| **log encoding** | Storing each channel as its EV relative to mid grey, scaled to 0–1 between a black and a white EV. The display transform's curve works on this. |
| **toe / shoulder** | The bottom and top bends of the display transform's S-curve: the toe eases shadows into black, the shoulder rolls highlights off toward white. |
| **inset / outset** | The display transform's matrices around the curve: **inset** pulls the primaries toward white so bright saturated colours fade to white without hue skews; **outset** gives back some of that saturation afterwards. |
| **chroma preservation** | The display transform's blend toward a luminance-only tone map that keeps each pixel's colour ratios, so bright colours stay colourful. |
| **local contrast** | The grade step that keeps detail where the display transform's curve is flat: log luminance is split into a **base** (broad areas, smoothed without crossing strong edges) and **detail** (the rest); the curve still places the base, and the detail is amplified so it keeps at least `detail_floor` contrast (ADR-0011). |
| **chroma** | How colourful a pixel is, independent of its lightness: the distance from grey in Oklab a/b. |
| **lens corrections** | Vignetting gain maps and distortion / colour-fringing warps a DNG carries for renderers (`OpcodeList3`). |
| **sharpening** | An unsharp mask on lightness at each output's final size. |
| **path to white** | How a colour behaves as it gets brighter: with a good display transform it desaturates smoothly toward white instead of clipping to a skewed hue. |
| **display-referred** | Values after the display transform (0–1, encoded for a screen). LUT operations usually run here. |
| **input space** | The colour space + transfer curve a LUT expects as input (e.g. `srgb`, `rec709`). |
| **transfer function** | The curve between linear and encoded values (sRGB curve, log). "Gamma" only in explanations. |
| **key** | Overall brightness character of a scene: `low_key`, `normal`, `high_key`. (Not used by normalise since ADR-0010.) |
| **EV / stop** | A doubling or halving of light. `exposure_ev: +1` = ×2 in scene-linear. |
| **white balance (WB)** | Per-channel gains making neutral objects neutral; **as-shot** = camera's recorded values. |
| **chroma NR / luma NR** | Noise reduction on colour / brightness detail. |

## Project management
| Term | Meaning |
|---|---|
| **milestone** | M0–M5 (and later). "Phase" is used only in the original brief. |
| **task** | One GitHub issue, 30–60 min, with acceptance criteria and a test plan. |
| **ADR** | Architecture decision record in `docs/decisions/`. |
