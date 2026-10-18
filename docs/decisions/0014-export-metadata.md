# ADR-0014: Exports carry allowlisted capture EXIF and a reproducible sidecar

**Status:** Accepted · 2026-10-17

## Context
Exports had no metadata: a photo library sorted them by file date, showed no camera, lens or exposure, and nothing tied an export back to the original and config that made it (project plan §4.4, #19, #20). An original's metadata is mostly about the RAW file (sensor geometry, DNG colour tags, the maker's private MakerNote) or about the camera's own JPEG processing (contrast, sharpness settings), and some of it is private (body serial numbers, GPS position). The repo is public and exports are often shared.

## Decision
1. **Capture EXIF by allowlist** (`decode/exif.py`): IFD0 make, model, date/time, artist and copyright, and from the EXIF directory the capture time (with sub-seconds and time-zone offset), the exposure settings and the lens. Everything else is dropped, including MakerNote, serial numbers, GPS and the camera's processing settings.
2. **Where it's read:** TIFF-based originals (DNG, ARW, NEF, CR2, PEF) directly; others (RAF, CR3, ORF, RW2) from the EXIF of the embedded camera JPEG. Unreadable metadata gives an export without capture EXIF, never a failed export.
3. **The export describes itself:** orientation upright (decode already rotated the pixels), colour space sRGB, its own pixel dimensions, `Software: picturesq <version>`.
4. **We write the EXIF block ourselves** (`export/exif.py`), with each tag's type from the EXIF 2.32 specification, because Pillow picks types from values (an exposure compensation of 0 became an unsigned rational) and ExifTool's validation flagged it.
5. **Sidecar** `<output>/<stem>.picturesq.json` per export, written after the JPEG: sidecar format version, picturesq version, original name + SHA-256, this output's settings and the `decode`/`normalise`/`grade` config (from sidecar format 2, #87, also this photo's `photos` overrides). No timestamps or paths, so two runs give identical bytes (tested, together with identical JPEGs).

## Consequences
- + Photo libraries sort and filter exports by capture time, camera, lens and exposure; ExifTool validates all six CC0 sample exports with no warnings.
- + A sidecar's `config` section is itself a valid `picturesq.yaml` body: an agent can reproduce or diff a render from it.
- − No location on exports. Wanting it is reasonable (an `archive` output for a photo library); it would be a per-output opt-in, not a default (follow-up issue).
- − Hashing an original reads it once more (~0.1 s for a 60 MB DNG).
- − A camera's wrong clock is copied faithfully (the reference set's Pocket 4 photos are dated 2000).
