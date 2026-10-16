# ADR-0009: M1 is judged at matched exposure

**Status:** Superseded by [ADR-0010](0010-camera-matched-neutral-render.md) · 2026-10-14

## Context
M1's exit criterion was "the neutral render is judged at least as good as the in-camera JPEG". M1 has no normalise stage, and the camera JPEG is not a neutral render: it applies its own tone curve and local tone mapping that lift shadows and midtones by 1 to 2 EV. Measured on the CC0 DJI sample (camera JPEG over our render, by camera-JPEG brightness band):

| Band | Camera / ours |
|---|---|
| near-black | +0.1 EV |
| deep shadow | +1.1 EV |
| shadow / low mids | +1.6 EV |
| mids | +2.1 EV |
| bright | +0.5 EV |
| brightest | +0.3 EV |

BaselineExposure is already applied, so this is not a missing gain. AgX (#17) keeps mid-grey roughly fixed, so it cannot close a midtone-exposure gap on its own; normalise (M2) is the stage that does. Judged literally, M1 would fail for a reason it does not own.

## Decision
M1 is judged at **matched exposure**. The comparison applies one global scene-linear EV offset, before the display transform, chosen so that our render's median luminance equals the camera JPEG's. M1 is judged on what it owns: colour, highlight roll-off, tonal shape, noise and detail. The bar becomes: comparable or better than the camera JPEG in colour and highlights at matched exposure; residual shadow differences from the camera's local tone mapping are expected.

The offset is an evaluation aid only: there is no config key and it has no effect on `run` or `export`. The stage sheet finds it by bisection (the display transform is non-linear, so there is no closed form). The comparison sheet (#24) shows the matched render and records the per-photo offset.

## Consequences
- + M1 has a gate it can pass or fail on its own merits.
- + The offsets recorded during the M1 review are target data for tuning M2's exposure algorithm.
- − Matching the median brightens the highlights by the same offset. With the v0 hard-clip display transform this blew the sky out; AgX (#17) rolls highlights off, so the matched panel now shows real highlight behaviour.
- − The camera's local tone mapping still differs in the shadows; the bar accepts that.

## Alternatives considered
- **Accept "darker in shadows" as M1's bar.** Rejected: a vague gate that cannot be failed and gives no data.
- **Move a minimal exposure step into M1.** Rejected: it would be a throwaway half-copy of normalise's key detection, partial correction and clamp, built before normalise is designed.
