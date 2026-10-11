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
