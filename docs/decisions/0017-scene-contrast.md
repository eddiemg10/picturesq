# ADR-0017: Scene contrast for flat scenes, off by default

**Status:** Accepted · 2026-10-18 · Amends [ADR-0010](0010-camera-matched-neutral-render.md) ("cameras don't normalise per scene") · Part of #60

## Context
ADR-0010 found that cameras brighten every photo by a near-constant amount and concluded that they don't normalise per scene. That holds for brightness. For contrast it doesn't hold on flat scenes.

The survey in #60 used 15 same-frame photos (6 CC0, 9 reference set). Each was decoded at half size and aligned with its camera JPEG. For each photo we measured the camera's extra contrast: the slope of the camera's display luminance against scene EV, divided by ours, over the photo's central range. We then compared that with the scene's **range**, the 5th to 95th percentile of scene luminance in EV:

- The relation is weak overall (r = −0.68; leave-one-out error 0.19 against 0.23 for the mean). **All of the signal comes from the two flat photos**, both DJI Pocket 4 reference-set photos: range 3.3 EV with ×1.52, and range 1.8 EV with ×1.38. Above 5 EV of range the ratio scatters between 0.62 and 1.13 and doesn't depend on the range.
- On those two photos the camera keeps the bright end where we put it and pushes the darker tones down. Its pivot is near the scene's p75–p90, not the median.
- A prototype added contrast in scene-linear at the end of normalise: `contrast = clamp(4.5/range − 1, 0, 0.5)`, then `contrast · 3 · tanh((EV − p75)/3)` stops, the same gain on R, G and B. It changed only those two photos (0.35 and 0.50); every other photo was untouched. On them the slope ratios went from 1.52/1.38 to 0.92/0.93, and the fine detail ratio against the camera went from 0.55–0.74 to 0.74–1.00. The reference gate's median |ΔEV| went from 0.24 to 0.17. Colour still passed, but one band (0.25–0.40) dropped to 0.82 against a limit of 0.80. The CC0 set didn't change.
- Stress test: with the threshold at 7 EV the prototype also reached a wide-range photo with clipped highlights. Its clipping rose from 0.35 % to 0.63 % and its slopes overshot. The threshold is what keeps wide scenes safe.
- The user compared variants and preferred a **gentle** version, half the prototype's contrast.

What we don't know: there is no photo with a range between 3.3 and 5.0 EV, so the threshold could be anywhere in that gap. Both photos are from one camera, so the effect may be DJI's alone.

## Decision
1. **Normalise gains a scene contrast step** (`normalise.scene_contrast`). It is a per-photo correction in scene-linear, placed after exposure and chroma NR:
   - `contrast = amount × clamp(target_range_ev / range − 1, 0, max_contrast)`. The defaults are `target_range_ev` 4.5, `max_contrast` 0.5 and `amount` 0.5. `amount` 1.0 is the prototype.
   - Each pixel moves by `contrast × soft_limit_ev × tanh((EV − pivot)/soft_limit_ev)` stops. The pivot is the scene's `pivot_percentile` (75) and `soft_limit_ev` is 3. R, G and B are multiplied by the same factor, so hue and saturation (the channel ratios) are kept.
   - It runs after chroma NR. Chroma NR keeps each pixel's luminance, so the measured range and pivot are the same either way. Chroma NR's fade by lightness also stays as it was fitted, and this is where the prototype ran (on normalised scenes).
2. **Off by default** (`enabled: false`). Two photos from one camera are not enough evidence to change every photo. A project can turn it on, and one photo can get it with `photos.<name>.normalise.scene_contrast` (an amount that replaces the project's and applies even when the step is off; 0 turns it off).
3. **Default amount 0.5 (gentle)**, as the user preferred on review, not 1.0, which matched the camera's slope on the two photos.
4. The applied contrast, range and pivot are recorded in each photo's stats (`scene_contrast`). `picturesq normalise` shows the contrast when it's above 0.
5. **Revisit** with 3–5 more flat same-frame photos (overcast, fog, snow, a flat beach; one non-DJI if possible). They decide the default (on or off), the threshold within 3.3–5.0 EV, and the amount.

## Consequences
- + Flat scenes can look like the camera's: on the two photos, the slope and detail gaps closed with the prototype's amount. The gentle default closes about half of the slope gap.
- + Wider scenes are bit-identical whether it's on or off. With it off (the default), every render is unchanged.
- − Off by default means the neutral render still differs from the camera on flat scenes until someone turns it on.
- − The fit rests on two photos from one camera. The threshold and pivot may not transfer to other makers.
- − With it on, stats are measured after scene contrast. The clip test then counts against a clip level that moved with exposure but not with the per-pixel gain, so it is approximate. A white balance override has the same caveat.
- ADR-0010's "cameras don't normalise per scene" now reads: cameras don't normalise *brightness* per scene, but they do give flat scenes extra contrast.
