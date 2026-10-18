# Architecture Decision Records

Short records of significant decisions. Format: Context → Decision → Consequences.
New ADRs get the next number; superseded ones are marked, not deleted.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-rawpy-decoder-no-darktable.md) | rawpy as the only decoder; no darktable dependency | Accepted |
| [0002](0002-no-camera-conversion-lut.md) | No camera conversion LUT; use DNG colour matrices | Accepted |
| [0003](0003-agx-display-transform.md) | AgX-style display transform as the neutral base | Accepted |
| [0004](0004-yaml-machine-owned.md) | YAML config is machine-owned; web UI is the human editor | Accepted |
| [0005](0005-web-ui-no-build.md) | No-build web UI (Starlette + htmx) with Python-rendered proxies | Accepted |
| [0006](0006-glossary-and-public-repo.md) | Binding glossary, British spelling, public repo | Accepted |
| [0007](0007-asset-licences.md) | Asset licences: AgX references and film-simulation LUT collections | Accepted |
| [0008](0008-derived-colour-matrices.md) | Derive colour matrices from primaries; never use rounded published matrices | Accepted |
| [0009](0009-m1-matched-exposure.md) | M1 is judged at matched exposure | Superseded by 0010 |
| [0010](0010-camera-matched-neutral-render.md) | The neutral render is fitted to camera JPEGs and gated on the real export | Accepted; decision 2 amended by 0011, saturation defaults by 0012, colour gate by 0013 |
| [0011](0011-local-contrast.md) | Local contrast keeps the detail the display transform's shoulder flattens | Accepted |
| [0012](0012-sky-colour.md) | DNG-specification colour matrices and a camera-matched blue rendering | Accepted |
| [0013](0013-pixel-aligned-colour-gate.md) | The colour gate compares chroma at the same pixels | Accepted; its reading of the near-white failure amended by 0016 |
| [0014](0014-export-metadata.md) | Exports carry allowlisted capture EXIF and a reproducible sidecar | Accepted |
| [0015](0015-parallelism-policy.md) | Threads within a photo, photos scheduled by memory, and both as machine settings | Accepted |
| [0016](0016-keep-as-shot-white-balance.md) | Keep the as-shot white balance; flag disagreement, never correct it | Accepted |
