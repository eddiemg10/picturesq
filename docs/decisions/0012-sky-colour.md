# ADR-0012: DNG-specification colour matrices and a camera-matched blue rendering

**Status:** Accepted · 2026-10-17 · Amends [ADR-0010](0010-camera-matched-neutral-render.md) (display-transform saturation defaults)

## Context
After ADR-0011 our exports matched the camera's brightness and detail, but blue skies were paler than the camera JPEG's and leaned purple (#54): on blue-sky pixels, pixel-aligned with the camera JPEG, ours had ~0.83× the camera's Oklab chroma and a median hue ~+5° toward purple (up to +10° on deep skies). The reference set's 0.55–0.70 lightness band, where Pocket 4 skies sit, was at 0.74× of the camera's chroma.

We measured where the difference comes from, step by step, on 10 same-frame photos with blue sky (CC0 samples and reference set):

1. **Not our display transform.** The lean is already there in the scene-linear decode (+7°). The display steps move it by a degree or two at most, and the gamut fit by ~0°. The hypothesis in #54 (desaturating blue in linear RGB bends it toward purple) is right in principle, but it isn't what made our skies purple.
2. **Part of it is a decode bug.** DNGs carry two colour matrices, measured under tungsten and daylight, which the DNG specification says to blend by the photo's white. LibRaw always uses the daylight one. Following the specification moves sky hue +4.9° → +3.6° and warm tones +2.9° → +0.9°.
3. **The rest is the camera's rendering choice.** Relative to an accurate render, the DJI Pocket 4's JPEG makes skies 1.2–1.6× more saturated (C/L), a little darker (Oklab L ~0.05 lower than our neutrals would predict) and ~4° more cyan. Fujifilm's JPEGs don't (0.94–0.96× saturation). Viewers remember skies as bluer and more vivid than they measure (a "memory colour"), and makers tune for it.
4. **Darkened, saturated skies are "paler" mainly because they are lighter.** At the same lightness and saturation they would match.

## Decision
1. **Decode uses the DNG-specification camera matrix** (`decode/dng_colour.py`, `decode.colour_matrix: dng`, default). The two colour matrices are blended linearly in inverse colour temperature (CCT by Robertson's method, as the Adobe DNG SDK does), solved by bisection on the weight because the Pocket 4's matrices make the usual fixed-point iteration oscillate. `ForwardMatrix`, `CameraCalibration` and `AnalogBalance` are honoured when present; the scene white is adapted to D65 with Bradford. White-balanced white maps to (1, 1, 1) as before. Non-DNG RAWs keep LibRaw's matrix; `colour_matrix: libraw` restores the old behaviour.
2. **A camera-matched blue rendering** (`grade.display_transform.blue_rendering`, `colour/blue_rendering.py`), the display transform's last step, in display-referred Oklab: a raised-cosine hue window (centre 250°, zero beyond ±70°) times a chroma ramp (0.01 → 0.05, so greys and whites are untouched); at full weight the hue turns −4° (toward cyan), chroma ×1.3 and lightness ×0.94. **On by default** for every camera, because the Pocket 4 is the primary camera and its JPEGs are the target (ADR-0010). **It can be turned off with `enabled: false`** (documented in `docs/configuration.md`), which leaves blues colorimetric.
3. **Out-of-gamut colours from that step are fitted at constant Oklab hue and lightness** (`colour/oklab.py::fit_gamut_oklab`, bisection on chroma), as in Ottosson's Oklab gamut clipping and ACES 2.0. The existing linear pull toward grey in the chroma-preservation and saturation steps stays: on our measurements it moves sky hue by ~0°, and replacing it would change every saturated colour for no measured gain.
4. **Saturation refitted:** `saturation` 1.25 → 1.15 and `saturation_fade` 1.0 → 0.7. With the matrix fix, midtones were 1.1–1.3× the camera's chroma; the lower boost fixes that, and keeping a little of it toward white keeps bright colours (clouds' edges, beaches) at the camera's chroma.
5. **Acceptance for #54, agreed with the maintainer:** blue-sky hue within ±3° (median) and chroma 0.9–1.1× of the camera's, and the colour gate passing on the reference set. The CC0 near-white band stays out of range for a reason this ADR doesn't address (below).

## Rejected
- **Applying the DNG `ProfileHueSatMap`** (DJI embeds one). A faithful DNG-SDK reference render with DJI's own profile (HueSatMap, then the `ProfileToneCurve` applied as the SDK does) still leaves deep skies +10° purple against DJI's JPEG, and the Pocket 4 table only reaches 1.15× saturation. DJI's JPEG engine is not its DNG profile.
- **A free-form per-hue table (hue × chroma or hue × lightness) fitted to the camera JPEGs**, the "camera-matching profile" approach (Adobe's camera-matching profiles, dcamprof). With 13 photos it overfitted: fitted on 12 photos and tested on the 13th, a 12-node hue table made held-out skies *worse* (hue +3.9°, chroma 0.85×). The three-amount window generalises: held-out sky hue +0.4°, chroma 1.01×.
- **Taking hue from the per-channel AgX branch** (darktable sigmoid's "preserve hue", inverted). It moves sky hue as needed (+0.3° median at 50 %) but brings back the per-channel orange → yellow skew on warm tones (+0.9° → +2.7°) and doesn't touch chroma.
- **A tone-mapping norm other than luminance** (max RGB, power, Euclidean) for chroma preservation: skies are only mildly saturated, so the norms barely differ there (sky chroma 0.83–0.87×).
- **Fading chroma preservation with scene brightness** (to whiten light sources, for the Pentax near-whites): no effect; those near-whites aren't light sources.

## Consequences
- + Skies match the camera: median blue-sky hue +0.2° and chroma 1.03× of the camera's (was +4.9° and 0.83×), on 10 same-frame photos with blue sky.
- + Full-resolution gate (`scripts/compare.py`), chroma ratio per lightness band:

  | set | before (ADR-0011) | after |
  |---|---|---|
  | reference | 0.89 1.04 1.05 **0.74** 0.86 0.88 | 0.93 1.03 1.07 0.96 0.92 0.81: **gate passes** (brightness 0.25 EV, no extra clipping) |
  | CC0 | **1.25** 1.19 1.13 0.95 1.02 **1.51** | 1.17 1.15 1.09 0.93 1.04 **1.56** (brightness 0.46 EV, no extra clipping) |
- + Warm and tungsten-lit scenes use the right camera matrix (the Pentax K-5 IIs interior takes 74 % of the tungsten matrix, the waxworks stage light 44 %).
- − **The CC0 colour gate still fails in the near-white band (1.56)**: both Pentax samples render a white card / blanket cream where the Pentax JPEG shows it white. The tint is already in the scene-linear decode with the DNG's own `AsShotNeutral`, so the camera's JPEG used a more neutralising white balance than it recorded. That is white-balance work (M2), tracked in #57; the gate comparing different pixels when brightness differs is #58.
- − Skies from other makers come out slightly more saturated than their own JPEGs (Fujifilm X-S10 ~1.14×). `blue_rendering.enabled: false` is the escape hatch.
- − Per-photo sky hue still varies around the camera's by −5.6 … +5.4°: the camera's sky rendering isn't a single fixed rotation.
- Cost: blue rendering converts each block to Oklab once (~0.3 s per 33 MP image); the DNG matrix is computed once per photo.
