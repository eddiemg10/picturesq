# ADR-0019: Grade operations, intensity and their order

**Status:** Accepted · 2026-10-18 · Part of #113

## Context
M3 adds looks. A look is a list of operations (plan §4.3), applied at an **intensity** between 0 % and 150 %. Three things need fixing before any look exists, because every operation and every look file depends on them:

1. **What intensity does to an operation.** Blending the finished image with the neutral render (an opacity) is simple, but it's wrong for most operations. Half of a +1 EV exposure blended with the original isn't +0.5 EV, and a blend of two white balances isn't a white balance. A look at 50 % should be the same look, half as strong.
2. **What 0 % means.** The plan promises that 0 % is exactly the neutral render. "Close to it" fails a byte-identical export test and makes the sidecar lie.
3. **Where operations run relative to local contrast and the display transform.** Today grade is local contrast (ADR-0011), then each output's display transform.

## Decision
1. **Intensity scales parameters, not pixels.** Every value that sets *how much* an operation does is declared with `scaled(neutral)` in its model (`picturesq.config.operations`). Its effective value is `neutral + intensity × (value − neutral)`. Values that say *where* or *which*, like the contrast pivot or a hue, are kept. So +1 EV at 50 % is +0.5 EV, and a 20-mired warmth at 50 % is 10 mired. The exception is `lut`: it has no parameters to scale, so it blends its output with its input (#119).
2. **Exactly neutral means skipped.** `apply_operation` returns the image untouched when the intensity is 0, or when every scaled value is at its neutral value after scaling. No operation has to be numerically perfect at neutral: a round trip through Oklab, for example, isn't bit-exact. Tests check bit-identity.
3. **Above 100 %, values may pass their declared range.** A look file's values are validated against each field's range. Scaled values are not, so each function keeps its own maths sane: contrast keeps a slope of at least 0.05 so tones never reverse, saturation never goes below grey, and white balance clamps the light it re-balances from to the table's 0–600 mired.
4. **Order:** the look's scene-linear operations → adjustments → local contrast → the display transform (per output) → the look's display-referred operations (`lut`, `grain`, `fade`; per output, before sharpening). They get display-linear Rec.709 values in 0–1.
   - Looks and adjustments come before local contrast. They move tones along the curve (exposure, contrast), and local contrast has to see where tones end up, because it restores detail exactly where the curve's shoulder and toe flatten it.
   - Adjustments come after the look's operations, so "a bit warmer" means the same thing on every look.
   - Display-referred operations come after the display transform. A LUT is built for display values, grain is a property of the print, not the scene, and fade lifts the print's black (a lift on sRGB values, as in grading tools).
5. **Units.** `white_balance.warmth` is in mired (positive is warmer). It re-balances from a light that many mired bluer than D65, so equal steps look equally strong at any temperature. `tint` uses the normalise scale (−1000 × Duv, positive is magenta). `contrast` works on luminance in log space around a pivot (0.18 by default) with the same gain on R, G and B, so hue and saturation are kept. `saturation` scales Oklab chroma, so lightness and hue are kept.

## Consequences
- + A look at 50 % is a gentler version of the same look, not a double exposure of two images.
- + Intensity 0 % and a project without a look give byte-identical exports (tested in #118).
- + New operations only declare which values are scaled. Scaling, skipping and the neutral check come for free.
- − An operation whose strength isn't one number (a tone curve's points) needs its own scaling rule: `tone_curve` moves each point toward the identity (#114).
- − White balance by chromatic adaptation changes a grey's luminance slightly (about 1 % at 60 mired), as raw converters' temperature sliders do.
