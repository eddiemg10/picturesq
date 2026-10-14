# ADR-0010: The neutral render is fitted to camera JPEGs and gated on the real export

**Status:** Accepted · 2026-10-14 · Supersedes [ADR-0009](0009-m1-matched-exposure.md)

## Context
ADR 0009 judged M1 at *matched exposure*: one EV offset per photo, chosen so our median equals the camera JPEG's. `picturesq run` never produces that image, so the real exports stayed 1.5–3 stops darker than the camera's while the matched panel looked fine, and nobody could tell whether we were getting closer. The plan also assumed the remaining gap needed per-photo exposure normalisation and local tone mapping.

We measured instead. For each CC0 sample and each reference-set photo with an embedded camera JPEG:

1. **Brightness:** the offset that matches the camera was **+2.3 ± 0.6 EV, nearly constant**. Regressing it on the scene's median, mean, p95 or p99 explained nothing (residual 0.56–0.59 EV against a raw spread of 0.59). Cameras do not normalise exposure per photo; their tone curve is simply brighter than ours.
2. **Tone curve:** matching brightness distributions photo by photo gives the camera's global curve (display luminance against scene EV). Its median across photos is reproduced within **0.07 stops RMS** (−6 to +3 EV) by exposure +1.96 EV and AgX with contrast 1.28, toe 2.1, shoulder 2.1.
3. **Local tone mapping:** after that global curve, the camera's block-by-block brightness relative to ours shows almost no compression on photos whose JPEG is the same frame (slopes within ±0.15). The larger slopes we saw came from embedded JPEGs of a *different frame* (see below).
4. **Colour:** mean Oklab chroma per lightness band showed us 1.2–1.3× more saturated than the camera in the shadows and midtones and **0.33× in the brightest band**: per-channel AgX washes bright colours (a blue sky) out far faster than cameras do.
5. **Embedded JPEGs are not always the same frame:** some DJI Pocket 4 DNGs (burst, portrait) embed a neighbouring frame.

## Decision
1. **The neutral render targets the camera JPEG.** Defaults are fitted to the measurements above, not chosen by eye:
   - `normalise.exposure.offset_ev: 2.0`, the same for every photo; `correction` (pull each photo toward a target median, for batch consistency) exists but is **off by default**.
   - `grade.display_transform`: contrast 1.3, toe 2.1, shoulder 2.1, `max_ev` 9.0.
   - `chroma_preservation: 0.7` blends AgX with a luminance-only tone map that keeps each pixel's colour ratios; `saturation: 1.25` with `saturation_fade: 1.0` (no boost left at white).
   - `normalise.chroma_nr`: chromaticity smoothing in the shadows (luminance kept; fades out 1.5 EV below mid grey).
   - Per-output sharpening (unsharp mask on lightness).
2. **No local tone mapping** for now. The data does not show cameras applying it beyond their global curve; it can be revisited with a same-frame counterexample.
3. **The gate is the real export** (`scripts/compare.py`, `picturesq.preview.compare`), against the embedded camera JPEG, on photos whose JPEG is the same frame (coarse luminance correlation ≥ 0.85):
   - brightness: median |ΔEV| ≤ 0.5 across the set;
   - colour: chroma per Oklab lightness band, pooled across the set, within 0.8–1.25 of the camera's;
   - highlights: no photo clips more than the camera + 0.5 %.
   The exposure-matched panel stays in the stage sheet as a diagnostic only.
4. **DNG lens corrections** (`OpcodeList3` gain maps and rectilinear warps) are implemented from the DNG specification but **off by default**: the only reference we have (the DJI sample's embedded JPEG) is itself uncorrected, so the warp could not be verified.

## Consequences
- + Exports look like the camera's out of the box. At the time of this ADR, on the 6 CC0 samples (full resolution): median |ΔEV| 0.43 and no photo clips more than the camera; on the same-frame reference-set photos: median |ΔEV| 0.25, no extra clipping.
- − The colour part of the gate does not pass yet, one band per set: CC0 near-white chroma is 1.56× the camera's (cameras render bright whites more neutrally; mostly one tungsten-lit photo), and the darkest CC0 band is 1.25× (more noise at full resolution than in the half-size tuning); the reference set's 0.55–0.70 band is 0.77×. These are the next targets.
- + Every rendering PR can show whether it moved us closer, with numbers.
- + Defaults have a recorded provenance (ADR-0007): fitted to measurements, not copied.
- − "Normalise" no longer evens out a batch by default. Batches look as consistent as the camera's own JPEGs; turning on `correction` trades camera fidelity for consistency.
- − Individual photos still differ by up to ~1.8 EV where the camera brightened a dark scene more (the Sony sample); no luma noise reduction; lens corrections unverified.
- − Full-resolution cost rose: a 33 MP photo takes ~38 s for both outputs (decode 3 s, normalise 8 s, web 4 s, archive 23 s) with ~1.75 GiB peak; #23 sets the budget.
- − Fitted to two camera families' JPEGs plus five CC0 cameras; other cameras' renderings may differ.
