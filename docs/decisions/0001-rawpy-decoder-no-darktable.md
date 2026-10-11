# ADR-0001: rawpy as the only decoder; no darktable dependency

**Status:** Accepted · 2026-10-11

## Context
We need to turn RAW files into linear RGB. Options: wrap darktable-cli or RawTherapee-cli (mature, excellent quality), or decode with rawpy (LibRaw) and own the rest of the pipeline.

## Decision
Use rawpy (LibRaw) as the only decoder. darktable is not a dependency. It is used only by hand during development, as a quality yardstick.

## Consequences
- + A pip-only install (~50 MB); works on Linux and Windows; 1000+ cameras.
- + Everything after decode is our numpy code, so YAML maps directly to parameters and proxies render in milliseconds.
- − darktable's XMP/styles store module params as versioned binary blobs, which can't be generated from YAML. Its per-render process startup also prevents live previews. Avoiding it removes both problems.
- − Denoise and highlight reconstruction are now our responsibility. Chroma NR is in v1; luma NR gets re-evaluated in M2 on night shots.
