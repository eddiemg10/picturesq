# Third-party LUTs in the look library

The `.cube` files below are not ours. They are bundled under **CC BY 4.0**
(full text: [`LICENSE-CC-BY-4.0.txt`](LICENSE-CC-BY-4.0.txt)), which allows copying and
redistribution, including in software under other licences, provided the authors are
credited, the licence is linked and changes are indicated (ADR-0020). Everything else in
picturesq is MIT.

| Look | File | Source | Original file | Credit | Changes |
|---|---|---|---|---|---|
| `cinematic/tungsten_night` | `cinematic/luts/tungsten_night.cube` | [TrondW/glassmeter-film-looks](https://github.com/TrondW/glassmeter-film-looks) (`luts/cube-srgb-33/`) | `cinestill-800t.cube` | Film simulations from GlassMeter by Glass Works (glass-works.ai) | Renamed (no film brand names in look names, ADR-0007); contents unchanged |
| `warm/portrait_film` | `warm/luts/portrait_film.cube` | same | `kodak-portra-400.cube` | Film simulations from GlassMeter by Glass Works (glass-works.ai) | Renamed; contents unchanged |
| `cinematic/neon` | `cinematic/luts/neon.cube` | [slaycamera/luts](https://github.com/slaycamera/luts) | `slay-03-neon.cube` | slay — slaycamera.com | Renamed; contents unchanged |
| `cinematic/deep_film` | `cinematic/luts/deep_film.cube` | same | `slay-04-film.cube` | slay — slaycamera.com | Renamed; contents unchanged |

Film names are trademarks of their owners; the GlassMeter LUTs are its authors' original
interpretations, not affiliated with or endorsed by the film makers. Each file keeps its
own header comments with the licence line.
