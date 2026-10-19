# ADR-0020: Bundle CC BY 4.0 LUTs, with credits

**Status:** Proposed · 2026-10-20 · Amends ADR-0007 (decision 4) · Issue #146

## Context
ADR-0007 decided to bundle no third-party assets, so the tree carried no licence obligations
and needed no NOTICE. Its reason was the sources on the table then: no licence (AgX),
GPL (Blender, darktable) or ShareAlike (RawTherapee's film simulations). None of those
allow bundling in an MIT tree without strings.

Grading a concert set (stage LEDs, haze, low light) showed that our own operations cover
contrast and colour well, but film-like colour responses are what LUTs are good at. Two
collections are licensed **CC BY 4.0** (checked 2026-10-20: the LICENSE file, GitHub's
licence field, and a licence line in each `.cube` header):

- GlassMeter film looks (TrondW/glassmeter-film-looks): 33³, sRGB in and out,
  display-referred, original curve sets ("original interpretations" of film stocks).
- slay LUTs (slaycamera/luts): 33³, input space undeclared (we assume sRGB, display-referred;
  a guess, checked only by eye on our renders).

CC BY 4.0 allows copying, redistribution and adaptation for any purpose, including in
software under another licence, on condition of attribution, a link to the licence and an
indication of changes. It has no ShareAlike clause, so it doesn't spread to our code. This
is an engineering reading of the licence, **not legal advice**.

## Decision
1. CC0, public-domain and CC BY 4.0 LUTs may be bundled in the look library. ShareAlike,
   NonCommercial, NoDerivatives, GPL and unlicensed files still may not (ADR-0007 stands
   for those).
2. Each bundled LUT is listed in `src/picturesq/grade/looks/CREDITS.md`: the look, the
   file, its source repository and original file name, the required credit line, and what
   we changed (only renames so far). The CC BY 4.0 text sits next to it, and a root `NOTICE`
   points to both. A test fails if a `.cube` in the library isn't listed.
3. Look names never use film brand names (ADR-0007); the original names stay in CREDITS.md.
4. A look built on a LUT says so in its description, with the licence.
5. When the UI gets an About panel (M4), it shows the credits.

## Consequences
- + Four film-like looks out of the box, including `cinematic/tungsten_night` (a tungsten
  night film look that suits stage light).
- − The tree is no longer licence-free: a NOTICE and a credits file must be kept current,
  and wheels ship CC BY files beside MIT code.
- − The slay LUTs' input space is assumed, not documented.
- Open: both collections are new (first published October 2026). If either changes its
  licence, the copies we have stay under the licence they were given under, but new
  versions would need checking again.
