# ADR-0007: Asset licences: AgX references and film-simulation LUT packs

**Status:** Accepted · 2026-10-12 · Issue #7

## Context
ADR 0003 says reference AgX implementations go through a licence check before any code is ported. The project plan (§14, question 3) also asks about RawTherapee's film-simulation **Hald CLUT** packs. picturesq is MIT-licensed and public, so anything we copy or bundle must be compatible with MIT redistribution.

This is an engineering reading of public licence texts, **not legal advice**. Uncertain points are marked **UNCERTAIN**. Sources were read on 2026-10-12.

Two principles used below:
- Copyright protects *expression* (source files, written text, a particular LUT file). It does not protect ideas, algorithms or mathematical facts. Re-implementing a published algorithm in our own code, written from the maths and not by translating the source, does not copy the expression.
- Whether a short list of constants (a matrix, a few curve parameters) is protectable is not settled and depends on jurisdiction. Matrices derived from public standards (Rec.2020 primaries, D65, sRGB) are facts. Hand-tuned "creative" numbers (a specific inset/rotation set) are a grey area. **UNCERTAIN.**

## Findings

| Asset | Source | Licence | Port maths? | Bundle files? | Attribution |
|---|---|---|---|---|---|
| Troy Sobotka's original AgX (OCIO config + LUTs) | github.com/sobotka/AgX | **None stated.** No LICENSE file, no licence in README, GitHub reports no licence | Maths: yes in principle (algorithm). Verbatim constants or tuned values: **UNCERTAIN**; avoid | **No.** All rights reserved by default when no licence is given | Credit in docs as courtesy |
| Sobotka AgX-S2O3 and SB2383-Configuration-Generation (config generators) | github.com/sobotka/AgX-S2O3, github.com/sobotka/SB2383-Configuration-Generation | **None stated** (no LICENSE file in either) | As above; read for the theory | **No** | Credit as above |
| AgXc (MrLixm) | github.com/MrLixm/AgXc | **None stated.** No LICENSE file in the repo tree; README describes it as a "fork" of sobotka/AgX. A fork of an unlicensed repo cannot grant more than its parent | As above | **No** | Credit as above |
| Blender's AgX (OCIO config + LUTs `AgX_Base_*.cube`) | `release/datafiles/colormanagement/` in github.com/blender/blender; maintained at github.com/EaryChow/AgX | Blender source is GPL-2.0-or-later / GPL-3.0 (per its COPYING and `doc/license/`). The config header says "See ocio-license.txt for details", but I could not find that file in the Blender repo. The EaryChow/AgX repo has no LICENSE file. **Licence of the config and LUTs: UNCERTAIN** | Maths: yes in principle. Do not translate Blender's scripts line by line | **No** (licence unclear, and may be GPL) | Credit in docs: Sobotka (original), Zhou, Faderbauer, Kapanen |
| darktable AgX module (`src/iop/agx.c`) | github.com/darktable-org/darktable | **GPL-3.0-or-later** (file header: "Copyright (C) 2025-2026 darktable developers") | **Only the published maths, re-derived by us.** Do not copy or closely translate the C code | **No** | Credit in docs. Cited sources (Desmos pages, forum threads) are separate public references |
| RawTherapee Film Simulation Collection (HaldCLUT.zip, version 2015-09-20) | rawtherapee.com/shared/HaldCLUT.zip; README inside the zip; docs at rawpedia.rawtherapee.com/Film_Simulation | **CC-BY-SA-4.0** for the collection, per the zip's README.txt. Credits: Pat David, Pavlov Dmitry, Michael Ezra | N/A (these are data, not maths). Deriving our own looks from them is a derivative: ShareAlike applies | **Not in the repo.** Allowed only as a separate, clearly licensed optional download | Credit authors, link the licence, indicate changes, keep the ShareAlike terms on the pack |
| `CreativePack-1` inside that collection | same zip, `Color/CreativePack-1/` | Covered by the README's blanket CC BY-SA 4.0 line, but the README credits no author for it. It is probably the PictureFX set by Marc Roovers, whose public posts show permission given case by case and no formal licence. **UNCERTAIN** (this is a guess) | N/A | **No** | Do not redistribute until the author is confirmed |
| Trademarked film names in file names | README disclaimer in the zip | Trademarks, not copyright. The pack claims fair use | N/A | N/A | Avoid film brand names in our own look names |

## GPL implications for an MIT project
- Copying GPL code (darktable, and Blender's source) into picturesq, or linking it, would make picturesq a derivative work that must be distributed under the GPL. That is incompatible with keeping the repo MIT. A line-by-line port to Python is still a derivative.
- Reading GPL code to understand an algorithm is fine. Writing our own implementation from the maths and published descriptions is fine. Do not paste GPL code into a prompt or a PR and ask for a "rewrite".
- Bundling GPL-licensed data files (LUTs, configs) next to MIT code does not change the code's licence, but it makes our distribution carry the GPL terms for those files. Not worth it.
- CC BY-SA 4.0 is a ShareAlike licence for content. Its compatibility with MIT code is not the question: a pack stays CC BY-SA, and anything derived from it must also be CC BY-SA. Keep it out of the MIT tree.
- "No licence stated" is not "free to use". Without a licence, the default is that nobody may copy or redistribute.

## Decision
1. **AgX display transform:** implement from the published maths only (the stages in ADR 0003: inset primaries, log encode, sigmoid, outset). Use public standards for colour matrices (Rec.2020, D65). Choose our own default parameter values in `picturesq.config` and tune them against our reference set, not by copying a reference implementation's tuned constants. No code, comments or file structure are copied from darktable, Blender, AgXc or Sobotka's repos.
2. **No verbatim assets bundled:** no OCIO configs and no `AgX_Base_*.cube` files from Blender, Sobotka or AgXc. Where a reference output is useful for tests, generate it locally in a script and do not commit it.
3. **Film-simulation packs:** not bundled and not a dependency. A later issue may add an optional `picturesq` command that downloads the RawTherapee collection to the user's cache, with its README and licence shown, and converts selected Hald CLUTs to `.cube` locally. Exclude `CreativePack-1` until its author and terms are confirmed. Our own first-party looks are authored by us (or from clearly licensed CC0 samples, see `reference/`).
4. **Attribution:** add a `NOTICE`/docs credit listing Troy Sobotka (AgX), the Blender AgX authors, and the darktable AgX module as inspirations for the maths. Add the pack credits for any downloaded pack.
5. **Ask the authors where it matters:** if we want Blender's exact tuned constants or any AgX LUT bundled, we ask the authors (or ask Sobotka to add a licence) first. This needs a human, so it is a follow-up and not a blocker.

## Consequences
- + The repo stays MIT with no third-party licence obligations in the tree.
- + Clean-room maths gives us full control of parameters (config over constants).
- − Our AgX will not match Blender's output exactly; we should compare visually, not bit for bit.
- − Film-look packs are a download step, not out of the box.
- − Open: whether short tuned constants are protectable, and the real licence of Blender's colour-management files. Revisit if we decide to match Blender exactly.
