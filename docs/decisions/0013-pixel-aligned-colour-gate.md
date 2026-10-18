# ADR-0013: The colour gate compares chroma at the same pixels

**Status:** Accepted · 2026-10-17 · Amends [ADR-0010](0010-camera-matched-neutral-render.md) (decision 3, colour) · Its reading of the near-white failure amended by [ADR-0016](0016-keep-as-shot-white-balance.md)

## Context
The colour part of the camera-match gate compares mean Oklab chroma per lightness band. Until now each image was banded by **its own** lightness: our pixels in our 0.85–1.0 band against the camera's pixels in the camera's 0.85–1.0 band. When a photo is brighter or darker than the camera's, those are different parts of the picture, so a brightness difference shows up as a colour difference (#58). Example: the Pentax K-5 IIs export is 0.75 EV darker than its JPEG, so the camera has a lit wall in its near-white band and we have a few lamp highlights.

Camera JPEGs are also not always framed like our export: the Pentax Q7 JPEG is a 3:2 crop of the 4:3 sensor (#61), and Fujifilm JPEGs are ~1 % tighter (in-camera distortion correction).

## Decision
1. **Bands come from the camera's lightness, chroma from the same pixel in both images** (`picturesq.preview.compare.aligned_chroma_by_band`). The question the gate asks becomes "where the camera shows a near-white, is our colour as strong as the camera's there?"
2. **Alignment** (`align`): crop ours (centred) to the camera JPEG's aspect, reduce both to a 1024 px long edge, try centred zooms of ours from 100 % to 93 %, find the remaining shift for each by phase correlation of luminance (at most 5 % of a side), and keep the zoom whose aligned pixels correlate best. The overlap is compared; the same-frame check (correlation ≥ 0.85) now runs on the aligned pair.
3. Thresholds, pooling across photos and the other two checks (brightness, highlights) are unchanged. `scripts/compare.py` still prints the old measure (each image banded by its own lightness) for reference; it doesn't gate.

## Consequences
Pooled chroma ratio per band (Oklab L 0–0.25, 0.25–0.40, 0.40–0.55, 0.55–0.70, 0.70–0.85, 0.85–1.0), full resolution, default config at the time of this ADR:

| set | own-lightness bands (before) | aligned (this ADR) |
|---|---|---|
| CC0 (6) | 1.18 1.15 1.09 0.93 1.04 **1.56** · FAIL | 1.06 0.89 0.99 1.01 1.06 **1.44** · FAIL |
| reference (9 same-frame) | 0.94 1.04 1.08 0.96 0.92 0.81 · PASS | 0.92 0.86 0.92 1.00 0.96 0.86 · PASS |

- + A brightness error can no longer be reported as a colour error; a test builds a darker image with the camera's exact colours and checks the aligned measure sees no difference while the old one fails the gate.
- + Alignment improved the same-frame correlation on the photos with framing differences (Pentax Q7 0.974 → 0.998, Fujifilm XQ1 0.929 → 0.966, X-S10 0.962 → 0.977) and lowered it on none by more than 0.001; the same 8 reference photos are excluded as different frames as before.
- + The CC0 near-white failure is real colour, not a measurement artefact: the Pentax K-5 IIs (2.07×), Pentax Q7 (2.47×) and Fujifilm XQ1 (1.78×) render near-whites more colourful than their cameras. That is white balance (#57).
- − Alignment is translation plus a centred zoom; a camera that corrects distortion strongly (barrel → rectilinear) would align well at the centre only. The correlation check would catch a bad case.
- − ~0.5 s more per photo in `scripts/compare.py`.

## Amended 2026-10-18: near-white passes on a small absolute difference
A band also passes when the mean chroma difference (ours minus the camera's, averaged over the photos that have the band) is within `CHROMA_ABS_TOLERANCE` = 0.015 Oklab chroma, as well as when the pooled ratio is in 0.8–1.25. Near-whites are nearly colourless in both images (camera ~0.007–0.016, ours ~0.018–0.022 on the CC0 samples), so their ratio is one of two tiny numbers: per photo up to 2.5×, while the differences stay at most 0.011, below the ~0.02 where a tint becomes noticeable. The user compared the side-by-sides and saw no difference they dislike. With it, the CC0 set passes colour (near-white ratio 1.44, difference +0.006; the other bands pass on the ratio as before) and the reference set still passes (differences −0.005 to +0.000). `scripts/compare.py` prints both measures and names the bands that passed on the tolerance.
