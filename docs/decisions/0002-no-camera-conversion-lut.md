# ADR-0002: No camera conversion LUT; use DNG colour matrices

**Status:** Accepted · 2026-10-11

## Context
The original brief assumed a "camera conversion LUT" stage. The DJI Osmo Pocket 4 shoots DNG stills; DJI's official LUTs convert **D-Log video** (log-encoded, wide gamut) to Rec.709.

## Decision
No camera LUT for stills. The DNG's embedded ColorMatrix/ForwardMatrix (applied by LibRaw) maps sensor RGB to a standard space. Proprietary RAWs use LibRaw's built-in per-camera matrices.

## Consequences
- + Removes the biggest risk in the brief (LUT input-space mismatch).
- + Works for every LibRaw camera with no per-camera assets.
- − Users who want "the DJI look" get it from a look recipe, not a vendor LUT. A D-Log encode path could be added later if DJI publishes the D-Log M curve.
