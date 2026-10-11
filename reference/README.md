# Reference set

Two sets of RAWs drive acceptance checks and golden tests. **Neither is committed** (both are git-ignored).

## 1. Pocket 4 set (`reference/raw/`): shot by you, local only
Shoot each scenario as **DNG + JPEG** if the camera allows it (the JPEG is our M1 comparison baseline). Name files freely; list them in `reference/raw/manifest.yaml` with the scenario id.

| id | Scenario | Why it's in the set |
|---|---|---|
| R01 | Easy daylight street, front-lit | Baseline: everything should look good |
| R02 | Deliberately underexposed (−2 EV) daylight | Auto-exposure must lift it without noise blow-up |
| R03 | Backlit subject against bright sky | Highlight protection vs shadow lift |
| R04 | Sunset / golden hour | WB estimator must *not* "correct" the warmth |
| R05 | Night city street, mixed lights | Low-key detection, chroma noise, mixed WB flag |
| R06 | Indoor tungsten / warm artificial light | WB disagreement flag |
| R07 | Portrait in open shade | Skin tones through every look |
| R08 | Landscape with foliage + blue sky | Saturated greens/blues, AgX hue stability |
| R09 | High-key: bright sand/snow/white wall | High-key detection; don't drag it to grey |
| R10 | High-ISO indoor (ISO ≥ 1600) | Noise behaviour, chroma NR |

Tips: keep the camera on auto for most shots (we want realistic auto mistakes). For R02, use exposure compensation −2.

## 2. CC0 samples (`reference/samples/`): fetched for CI
A few small RAWs from other cameras (public domain, https://raw.pixls.us) prove "any LibRaw camera" works.
They are listed with checksums in `reference/samples.json` and downloaded by:

```bash
uv run python scripts/fetch_samples.py
```
