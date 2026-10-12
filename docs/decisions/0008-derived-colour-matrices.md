# ADR-0008: Derive colour matrices from primaries; never use rounded published matrices

**Status:** Accepted · 2026-10-12

## Context
Converting linear RGB between colour spaces is a 3×3 matrix. Standards print these matrices rounded: the sRGB standard (IEC 61966-2-1) gives XYZ → sRGB to 4 decimals. colour-science's default `sRGB` space uses that published matrix, so Rec.2020 → sRGB maps white `[1, 1, 1]` to `[0.99984, 1.00010, 1.00007]`: a 1.6e-4 error that tints pure white very slightly and makes "white maps to white" and "matches colour-science to 1e-6" impossible to satisfy together (#11).

## Decision
picturesq derives every RGB ↔ XYZ matrix from the space's primaries and white point (xy chromaticities) in float64 at import time (`colour/spaces.py`). Tests compare against colour-science spaces built with `use_derived_matrix_*=True`, and check published matrices (ITU-R BT.2087) only to their printed precision.

## Consequences
- + White and grey are preserved exactly (to float64 precision), so a neutral photo stays neutral through every conversion.
- + One rule for every space we add later (AgX's inset space, Display P3).
- − Our sRGB numbers differ from software that uses the published matrix by up to ~1e-4. That is far below an 8-bit step (1/255 ≈ 4e-3) and invisible in exports.
