# Reference set

Two sets of RAWs drive acceptance checks and golden tests. **Neither is committed** (both are git-ignored).

## 1. Pocket 4 set (`reference/raw/`): shot by you, local only
The reference set is **private**: no RAWs, crops, proxies or goldens derived from it are ever committed. Tests that need it are marked `@pytest.mark.reference` and skip when `reference/raw/` is absent, so CI never sees it. Run them locally with `uv run pytest -m reference` before each milestone review.

Shoot each scenario as **DNG + JPEG** if the camera allows it (the JPEG is our M1 comparison baseline). Name files freely; list them in `reference/raw/manifest.yaml`:

```yaml
photos:
  - id: R01                 # scenario id below (X01, X02, … for extras)
    raw: DJI_..._0270_D.DNG
    jpeg: null              # in-camera JPEG of the same frame, if any
    status: ok              # ok | stand-in
    sha256: …
    notes: "…"
```

A **stand-in** is an existing photo that covers a scenario until a proper shot exists.

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
Small RAWs from other cameras (public domain, https://raw.pixls.us, licence checked per file) prove "any LibRaw camera" works.
They are the only real RAWs CI sees, so they deliberately cover what the private set can't bring to CI:

| Sample | Format | Covers |
|---|---|---|
| `dji-fc4382.dng` | DNG, Bayer | BaselineExposure +1.32 EV (like the Pocket 4); bright sky over dark land |
| `pentax-k5iis.dng` | DNG, Bayer | BaselineExposure ≈ +0.49 EV; tungsten interior |
| `pentax-q7.dng` | DNG, Bayer | black level 0 (like the Pocket 4); dark low-key interior, ISO 800 |
| `sony-ilme-fx3.arw` | ARW, Bayer | non-DNG RAW; warm indoor light at ISO 20000 |
| `fujifilm-xq1.raf` | RAF, X-Trans | 6×6 colour filter pattern; daylight at −1 EV |
| `fujifilm-x-s10.raf` | RAF, X-Trans | colour chart, for colour accuracy checks |

No CC0 night street scene exists on raw.pixls.us, and there are no Pocket 4 samples. About 100 MB in total, listed with checksums in `reference/samples.json` and downloaded by:

```bash
uv run python scripts/fetch_samples.py
```
