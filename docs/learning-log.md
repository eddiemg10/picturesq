# Learning log

Short entries: **concept**, a one-paragraph explanation, and **why it mattered in the code**.
Agents append here as phases introduce new concepts.

---

## 2026-10-11 · RAW files and decoding
A RAW file is not an image. It holds one brightness number per sensor pixel, where each pixel sits under a red, green or blue filter in a checkerboard (Bayer mosaic), plus metadata on how to interpret them. A **decoder** subtracts the sensor's black level, scales to the white level, **demosaics** (estimates the two missing colours per pixel from neighbours), applies white-balance multipliers, and converts the camera's colour primaries to a standard space using a **colour matrix**. The result is a linear RGB image.
**Why it mattered:** this is the only camera-specific step. After decoding, everything is camera-agnostic, which is why picturesq supports any LibRaw camera (ADR-0001).

## 2026-10-11 · D-Log LUTs don't apply to DNG
DJI's "conversion LUTs" turn D-Log *video* into normal-looking Rec.709. D-Log is a log curve plus a wide gamut that the camera bakes into video files. A DNG still is linear sensor data with no log encoding. Applying a D-Log LUT to it means feeding the LUT inputs it was never designed for, and the colours and contrast come out wrong. A LUT only gives correct results when the input is in exactly the colour space and transfer curve it was built for.
**Why it mattered:** we dropped the camera-LUT stage entirely (ADR-0002), and every user `.cube` file must declare its input space.

## 2026-10-11 · Linear vs display encoding
In **scene-linear** data, a value is proportional to light: double the light, double the number. Displays and JPEGs use a **non-linear encoding** (sRGB "gamma"), which spends more code values on shadows because human vision is more sensitive there. Maths that mimics physics (exposure, white balance, blending light) must happen in linear. Doing it on gamma-encoded values distorts contrast and colour, a classic mistake.
**Why it mattered:** the whole pipeline works in float32 linear and converts to sRGB only at export.

## 2026-10-11 · Display transforms (tone mapping)
A sunny scene can span 15+ stops; a screen shows about 6–8. A **display transform** compresses scene-linear values into the 0–1 display range: it decides how highlights roll off, how contrast feels, and how bright saturated colours fade toward white. Naive per-channel curves skew hues (skies turn cyan, sunsets yellow). AgX and OpenDRT are open designs that avoid this.
**Why it mattered:** AgX is our neutral base (ADR-0003); every look builds on it.

## 2026-10-11 · The memory maths of a 33 MP photo
7680 × 4320 ≈ 33 M pixels. As float32 RGB that's 33M × 3 × 4 bytes ≈ **400 MB per array**. A numpy expression like `a * b + c` allocates temporaries, so a naive chain can peak at 1–2 GB per image. On an 8 GB laptop, memory, not CPU, limits how many photos run in parallel. Per-pixel ops on a 1000 px proxy (~0.5 MP) are ~60× cheaper, which is why interactive previews always use proxies.
**Why it mattered:** proxy-first design, in-place ops, memory-capped worker pool, and memory budget tests (project plan §5).

## 2026-10-11 · Proxies
A **proxy** is a small (2048 px long edge), cached, **scene-linear** float16 copy of a photo; the term comes from video editing. It has ~14× fewer pixels than a 33 MP original, so operations take milliseconds. It's scene-linear rather than a JPEG thumbnail, so normalise and grade behave exactly as they will on the original: what you preview is what you export. Float16 halves storage versus float32 while still holding values above 1.0 (bright skies), which 8-bit can't. The cache key hashes the original, the decode config and the version, so a proxy is never stale. A **preview** is the display-ready render *of* a proxy.
**Why it mattered:** every interactive feature (contact sheets, the UI, normalise stats) uses proxies; only export touches originals. This is what makes an 8 GB, CPU-only laptop enough.

## 2026-10-12 · Inside a Pocket 4 DNG
A DNG is a TIFF holding several images: IFD0 has a 160×90 thumbnail plus all metadata, and sub-IFDs hold the **raw data** and a **720×1280 JPEG preview** (the camera's own rendering). Surveying ~350 Pocket 4 DNGs (`Model: OP-041`) showed: the raw is a **Bayer mosaic** (`R G / G B`), not a linear DNG, so demosaicing is ours to do; it's stored **uncompressed** in 16 bits (≈ 41 MB at 21 MP, 64 MB at 33 MP); **black level 0** (most cameras report a few hundred, so the camera likely subtracts it already) and **white level 62400**; two **colour matrices** (calibrated under tungsten and D65) that a renderer blends according to white balance; and `AsShotNeutral`, the camera's white balance, *recorded but not applied*. Three raw sizes appear: 7680×4320 (33 MP), 6144×3456 and 6144×3584 (21–22 MP, portrait). rawpy reported an all-zero `rgb_xyz_matrix` for these files.
**Why it mattered:** demosaic quality matters for this camera; the embedded preview is too small for a full-size in-camera baseline, so we shoot JPEG+DNG; and decode (#15) must check whether LibRaw really applies the DNG colour matrices before we trust its colours.

## 2026-10-12 · BaselineExposure: the camera underexposes on purpose
The Pocket 4 records the raw **2–4 stops darker** than the final image should look, so bright highlights don't clip: in ~350 photos, none had more than 1 % of pixels near white. The DNG tag `BaselineExposure` tells renderers how many stops to brighten (×2 per stop), and it **varies per photo** (from about +0.6 to +4 EV). The median raw pixel of a normal daylight photo sits at only ~2–6 % of white. So "underexposed" only means something *after* BaselineExposure is applied.
**Why it mattered:** decode must read BaselineExposure per file, or every render comes out ~3 stops dark; normalise measures exposure after applying it; and the AgX display transform has to roll off the highlights this headroom preserves instead of clipping them.

## 2026-10-12 · Bit depth and quantisation
*n* bits give 2ⁿ values: an 8-bit JPEG channel is a whole number from 0 to 255. Storing continuous light means rounding to the nearest step (**quantisation**). Steps are invisible until you stretch them: brighten a dim sky that spans 20 JPEG values by 2 stops and it still has only 20 values, now 4 apart, so you see **banding**. In a linear encoding each stop down gets half the remaining steps (8-bit linear: 128 steps in the top stop, 4 in the stop five below). JPEG's gamma curve spends more on shadows (~15 there), which is fine for viewing but not for editing. A Pocket 4 raw spans 0–62400 (≈ 975 steps even five stops down; one photo used 16,899 distinct values).
**Why it mattered:** float32 internally, 16-bit intermediates, and 8-bit only at final export (AGENTS.md). Every adjustment happens while there are still plenty of steps.

## 2026-10-12 · Why shoot RAW when the output is a JPEG
A camera JPEG is the camera running its *own* pipeline and discarding the inputs: white balance, highlight handling, tone curve, noise reduction and sharpening are baked into 8 bits. A RAW keeps those decisions open: WB is two numbers in metadata, highlights above display white survive (up to ~2 stops in our photos), and shadows have thousands of steps. picturesq applies the look in scene-linear float *before* the display transform and 8-bit export, so it works on the full data. For easy, well-exposed scenes the camera JPEG can be close; the gap shows up in hard scenes (sun in frame, night, mixed light) and in batch consistency, since normalise must measure each photo's real exposure rather than undo a per-frame auto-correction.
**Why it mattered:** this is the case for the whole tool, and why the M1 exit criterion compares our neutral render against the in-camera JPEG.
