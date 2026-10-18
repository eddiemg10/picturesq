# ADR-0018: The white level comes from the original, not from the frame's brightest pixel

**Status:** Accepted · 2026-10-18 · Resolves #94

## Context
LibRaw has a convenience, `adjust_maximum_thr` (rawpy default 0.75). If a photo's brightest raw value is above 75 % of the **white level** the original specifies, LibRaw assumes that value is the real white level and scales the whole photo to it. So a photo's brightness depends on what's in the frame, and its brightest pixels are decoded as if the sensor had clipped there. It was found while writing `clip_level` for photo info (#79, PR #93).

We measured it with half-size decodes and the default config, at 0.75 and at 0:

- **CC0 samples.** It changes two of the six photos, the DJI FC4382 (brightest raw value 0.917 of the white level, ×1.090 brighter at 0.75) and the Pentax Q7 (0.867, ×1.154). The others peak at or above the white level (XQ1, K-5 IIs) or far below 0.75 (X-S10 0.34, FX3 0.17), and decode identically either way.
- **The Pocket 4 reference set (17 photos).** None changes. Each photo's brightest raw value is either at most 0.55 of the white level or above it (truly clipped); none falls between 0.75 and 1.0. The gate result is identical both ways (median |ΔEV| 0.241, PASS).
- **Content dependence, shown directly.** We added a 16 px spot at 80 % of the white level (a small lamp or reflection) to the raw data of a sample that peaks at 17 %. At 0.75 the rest of the photo came out ×1.25 brighter; at 0 it was bit-identical on a Bayer sensor. On the X-Trans sample (X-S10), LibRaw's half-size decode moves other pixels by about 1 % even at 0, with the median unchanged. That is a separate effect, not the white level.
- **Clipped highlights at 0.** LibRaw's convenience exists for files whose specified white level is higher than the sensor really reaches; there, highlights that clipped would stop short of white. On the two CC0 samples with real sensor clipping, clipped whites still reach the clip level (XQ1 1.000, K-5 IIs 1.004) and stay neutral at 0.
- **The cost.** The two samples it changes were already darker than their camera JPEGs, and at 0 they are darker still: DJI −0.36 → −0.56 EV, Q7 −0.18 → −0.45 EV. The CC0 brightness gate goes from 0.46 (PASS) to 0.56 (FAIL, limit 0.5). Chroma and highlights still pass.

## Decision
1. **The white level comes from the original** (`decode.adjust_white_level: 0`, passed to LibRaw as `adjust_maximum_thr`). Same scene, same brightness, whatever else is in the frame. That is what batch consistency needs, and it makes `clip_level` exact.
2. **The setting stays available** (0 to under 1; LibRaw's 0.75 is the old behaviour) for a camera whose files specify a white level its sensor never reaches.
3. **The exposure offset is not refitted.** It was fitted on the Pocket 4 set, which doesn't change.
4. **The CC0 brightness gate is left as it is, and now fails.** It passed only because LibRaw happened to brighten these two photos toward their camera JPEGs; the camera's own brightness doesn't depend on the brightest pixel. The other CC0 cameras already sit below their JPEGs (FX3 −1.77, K-5 IIs −0.76, X-S10 −0.56 EV): the offset is fitted to one camera. Whether the brightness gate should apply to other cameras is decided when M2 closes. Until then the DJI sample's brightness check in `tests/integration/test_camera_match.py` is a strict expected failure.

## Consequences
- + A small bright object can no longer shift a whole photo's brightness. Tested: `tests/integration/test_decode_raw.py` adds a spot to the raw data.
- + `clip_level` no longer needs a caveat for unclipped photos.
- + Pocket 4 renders are unchanged.
- − The DJI and Q7 samples render 0.12 and 0.21 EV darker in scene terms (0.20 and 0.27 EV against their camera JPEGs), and the CC0 brightness gate fails until it is reconsidered.
- − A camera whose files overstate the white level would show clipped highlights short of white; none of our samples does. The setting turns LibRaw's behaviour back on.
- Proxies rebuild once: the decode config, which keys them, gained a key.
