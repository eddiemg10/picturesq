# ADR-0011: Local contrast keeps the detail the display transform's shoulder flattens

**Status:** Accepted · 2026-10-16 · Amends [ADR-0010](0010-camera-matched-neutral-render.md) (decision 2, "no local tone mapping")

## Context
After ADR-0010 our exports matched the camera's brightness and global tone curve, but skies and horizons looked flat: clouds barely visible, distant hills lost in haze (DJI sample, PR #53 review). Measured pixel by pixel against the camera JPEG:

1. **The global curve is not the problem.** Binned by scene EV, the median display brightness across the 13 same-frame photos (CC0 + reference set) agrees with the camera's within ~0.1 stop from −3 to +5 EV.
2. **Detail is.** Within the DJI sky (scene +3 to +4 EV), the camera's brightness varies 0.205 stops (std) and ours 0.056: about **4×** less local contrast. Our curve's slope at +3.5 EV is 0.19 display stops per scene stop (it is 1.3 at mid grey), so a 0.3-stop cloud becomes 0.06 stops. The camera keeps a slope of about 0.7 there for detail while placing the sky as a whole on the same global curve.
3. In the midtones the camera also has ~1.2× (median, −0.22 stops) more local contrast (high-pass at 1 % of the long edge) than ours.

ADR-0010 ruled out local tone mapping because the camera showed no compression of *broad* areas beyond its global curve. That still holds. What it does do is keep *detail* steeper than its global curve: that is what a base/detail tone mapper does, and what a single per-pixel curve cannot.

## Decision
1. Add **local contrast** (`grade.local_contrast`, `grade/local_contrast.py`), a scene-linear grade step before the display transform:
   - split log luminance into a **base** and **detail**; the base is an edge-aware blur (domain transform recursive filter, Gastal & Oliveira 2011) of a ≤ 512 px copy, with spatial scale `radius` (5 % of the long edge) and range scale `edge_ev` (1 stop);
   - bring the base to full resolution by **joint bilateral upsampling** (neighbours weighted by brightness similarity), so pixels next to a horizon never take the other side's base;
   - amplify detail by `max(slope(B), detail_floor) × amount / slope(B)` (capped at `max_gain`), where `slope(B)` is the display transform's luminance slope at the base. The floor (0.8) applies above mid grey only, so shadow noise is not lifted; `amount` (1.15) applies everywhere;
   - amplify small detail only: the added stops level off at `(gain − 1) × detail_limit_ev` (0.25), so a sun glint several stops above the water isn't pushed into white;
   - scale R, G and B by the same factor, so hue and colour ratios are kept.
2. Defaults were chosen against the same-frame camera JPEGs (high-pass contrast per scene-EV band) and checked visually on the DJI sample.
3. Rejected along the way: a self-guided filter for the base (it leaves part of a strong edge in the detail, which the sky's high gain turned into a 1.5-stop halo above a synthetic horizon; fading the gain near edges removed the halo but also most of the effect on real textures), and the fast guided filter's coefficient upsampling (a one-pixel bright line along the edge). Without `detail_limit_ev`, a 2048 px render of the sun-over-sea reference photo clipped 0.73 % (0.22 % without local contrast; 0.37 % with the limit).

## Consequences
- + Clouds, haze layers and distant ridges are back. Local contrast relative to the camera, median across same-frame photos (log2 ours/camera): midtones −0.22 → −0.01, highlights 0.00 → +0.12, DJI sky −0.71 → −0.23.
- + No measurable halo: a 6-stop synthetic horizon changes by < 0.01 stop (tested).
- − Deep shadows get `amount` (1.15×) more contrast, including noise; they already had more local contrast than the camera (+0.45 stops), which luma NR has to address.
- − Cost: ~3.5 s on a 12 MP photo and ~6 s on 26 MP at full resolution, ~100 MB extra peak.
- − The camera's per-scene behaviour varies (DJI sky −0.23, Fuji XQ1 −0.59, some reference photos +0.3 to +0.5): one set of defaults can't match all of them.

## State after this ADR
- Brightness and highlight gates pass on both sets. The colour gate still fails as it did before local contrast: bright blues (skies) are ~0.8× the camera's chroma and lean ~5° toward purple. Tracked in #54, together with the DNG `ProfileHueSatMap` the DJI files carry.
- Dark speckle inside sun glints predates local contrast: #55.
