# ADR-0016: Keep the as-shot white balance; flag disagreement, never correct it

**Status:** Accepted · 2026-10-18 · Amends [ADR-0013](0013-pixel-aligned-colour-gate.md) (its reading of the CC0 near-white failure) · Resolves #57

## Context
On the CC0 samples the colour gate fails one band: near-whites (Oklab L 0.85–1.0) are 1.44× as colourful as the camera's (target 0.8–1.25). ADR-0013 attributed it to white balance: the Pentax K-5 IIs white card renders cream where the camera's JPEG is white. If cameras neutralise more than the white balance they record, normalise should correct toward neutral, at least under warm light. The plan (D6) had the opposite default: keep the as-shot white balance and only flag photos whose white balance looks wrong (`wb_disagreement`, #83).

We measured it (#57; half-size decodes, 2048 px renders):

1. **The white the camera JPEG uses.** We aligned our render with the camera JPEG (ADR-0013), took pixels the camera renders neutral (Oklab C < 0.02, L 0.55–0.95, unclipped) and solved for the Bradford white that maps ours onto the camera's. On all **15 same-frame photos** (6 CC0, 9 reference) it is within **15 mired** of our as-shot white (median 2). That includes all 9 DJI Pocket 4 photos (−4.4 to +3.2 mired) and warm-light photos at 4150 K and 4260 K (+3.2 and −0.2). The one larger value is the Pentax K-5 IIs under tungsten (3332 K): +14.5 mired, so its camera adapts slightly *more* than it records.
2. **Correcting to the camera's own white** ("oracle") moves the CC0 near-white band only 1.49 → 1.44. Per photo:
   - Pentax K-5 IIs: 2.07 → 1.16. A real white-balance difference.
   - Pentax Q7: 2.71 → 2.68. Not white balance: the camera desaturates highlights (near-white chroma 0.0024 against our 0.0167 above L 0.95), with the same hue.
   - Fujifilm XQ1: 1.92 → 2.29. Fine-scale colour scatter (a 2 px blur takes it to 1.34; the camera also clips 1.4 % against our 0.1 %).
3. **Estimating the light from the photo** is noisy. Against the as-shot white, the median error is 18–21 mired for grey world, grey world on near-neutral pixels, brightest pixels and grey edge, over 23 photos. Corrections driven by an estimator "pass" the CC0 band only by moving other photos away from the camera's white (for example −61 and +54 mired on two photos whose cameras agree with as-shot within 10), and they drop the lower bands to 0.83.

## Decision
1. **Normalise keeps the as-shot white balance.** There is no automatic correction, not even a partial one that is off by default: the data shows it would move us away from the camera more often than toward it.
2. **`wb_disagreement` is information only.** It is raised when *both* estimates (`brightest` and `grey`, #83) differ from the as-shot white by at least `flag_disagreement_mired` (30) **in the same direction**. On the 23 photos this flags 3: the Sony FX3 night shot (+88/+87 mired) and two reference photos under strongly coloured light. Requiring both keeps one estimator's failure (a stage light that pulls `brightest` 240 mired off) from raising a flag.

   **Amended 2026-10-18: the flag is opt-in** (`normalise.white_balance.flag_disagreement`, default `false`). On the 17-photo reference set it flagged 3 photos (a sunset road, a tree-lined road under blue sky, a club with mixed light) and none were wrong: since the camera keeps its recorded white balance (point 1 above), the flag mostly fires on scenes that are genuinely coloured. The check still runs and its numbers are recorded in the stats.
3. **The fix for a photo is an override** (`photos.<name>.normalise.wb_kelvin` / `tint`, #87), chosen by a person or an agent looking at the flag.
4. **The CC0 near-white band stays failing** with these three causes recorded instead of white balance:
   - **Pentax K-5 IIs:** a ~15 mired extra adaptation under tungsten. One sample is not enough evidence for an "incomplete adaptation" setting; revisit with more warm-light same-frame photos.
   - **Pentax Q7:** the camera's highlights desaturate toward white sooner than ours, a path-to-white question for the display transform (#98).
   - **Fujifilm XQ1:** fine-scale chroma scatter at near-white, a noise/X-Trans demosaic question (#99).
   The reference set, the acceptance set for the DJI Pocket 4, passes every band.

## Consequences
- + The neutral render stays as close to the camera as it can be: the camera's white matches as-shot on every same-frame photo we have.
- + A wrong as-shot white balance (rare: mixed or coloured light) is visible in the stats (and flagged, with `flag_disagreement` on) and fixed with a one-line override, never a silent change.
- − The CC0 gate keeps failing its near-white band until #98/#99; M2's exit criterion accepts this ADR in place of that band passing.
- − The near-white band compares chroma around 0.007–0.02, close to the noise floor, so its ratio is sensitive to small absolute differences. Whether the gate should allow an absolute tolerance there is an open question for the user.
- − Fujifilm and Sony as-shot whites are approximate (LibRaw's matrix; no DNG tags), and three camera-implied whites rest on few neutral pixels (327–2492).
