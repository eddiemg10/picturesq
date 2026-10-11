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
