# Configuration

Each project folder has one config file, `picturesq.yaml`, next to the originals:

```
lisbon/
  DJI_0001.DNG
  DJI_0002.DNG
  picturesq.yaml
```

You don't need to write it: `picturesq run` creates it with defaults, and `picturesq ui` edits it for you. Coding agents can edit it directly. Every key is optional, so an empty file (or `{}`) means "all defaults".

> **Status:** config format version `1`, pre-alpha. This page documents what exists today (`decode`, `normalise`, `grade.local_contrast`, `grade.display_transform`, `export`). Sections for looks, adjustments and per-photo overrides are added as those stages ship.

## Defaults

This is the complete file with every default written out:

```yaml
version: 1
decode:
  demosaic: ahd
  highlight_mode: blend
  lens_corrections: false
  baseline_exposure: true
normalise:
  enabled: true
  exposure:
    offset_ev: 2.0
    correction: 0.0
    target_ev: -1.0
    max_correction_ev: 2.0
  chroma_nr:
    amount: 1.0
    radius: 0.004
    full_lightness: 0.2
    fade_lightness: 0.4
grade:
  local_contrast:
    enabled: true
    detail_floor: 0.8
    amount: 1.15
    radius: 0.05
    edge_ev: 1.0
    detail_limit_ev: 0.25
    max_gain: 4.0
  display_transform:
    min_ev: -10.0
    max_ev: 9.0
    contrast: 1.3
    toe: 2.1
    shoulder: 2.1
    inset:
    - 0.25
    - 0.25
    - 0.25
    chroma_preservation: 0.7
    saturation: 1.25
    saturation_fade: 1.0
    outset:
    - 0.35
    - 0.35
    - 0.35
export:
  outputs:
    web:
      long_edge: 2048
      quality: 90
      sharpen:
        amount: 0.5
        radius: 0.8
    archive:
      long_edge: null
      quality: 95
      sharpen:
        amount: 0.3
        radius: 1.2
  enabled:
  - web
  - archive
```

## Examples

Write only web-sized JPEGs:

```yaml
export:
  enabled: [web]
```

Add an Instagram output and write it together with the web output:

```yaml
export:
  outputs:
    web: {long_edge: 2048, quality: 90}
    instagram: {long_edge: 1080, quality: 85}
  enabled: [web, instagram]
```

A punchier, more saturated neutral render:

```yaml
grade:
  display_transform: {contrast: 1.5, saturation: 1.4}
```

Make every photo in a batch about equally bright (cameras don't do this; it is off by default):

```yaml
normalise:
  exposure: {correction: 0.6, target_ev: -1.0}
```

No sharpening on the web output:

```yaml
export:
  outputs:
    web: {long_edge: 2048, quality: 90, sharpen: {amount: 0}}
    archive: {long_edge: null, quality: 95}
```

Setting `outputs` replaces the default outputs entirely, so list every output you want to keep (`archive` isn't defined above, so it can't be enabled).

## Reference

### Top level

| Key | Type | Default | Description |
|---|---|---|---|
| `version` | `1` | `1` | Config format version. Only `1` is accepted. |
| `decode` | mapping | see below | How RAW originals are decoded. |
| `normalise` | mapping | see below | Per-photo corrections: exposure and colour noise reduction. |
| `grade` | mapping | see below | How images are rendered for display. Today only the display transform. |
| `export` | mapping | see below | Which files `picturesq export` writes. |

### `decode`

| Key | Type | Default | Description |
|---|---|---|---|
| `demosaic` | `linear` \| `vng` \| `ppg` \| `ahd` \| `dcb` \| `dht` \| `aahd` | `ahd` | Algorithm that reconstructs full colour from the sensor's colour-filter mosaic. `linear` is fastest and softest. `ahd`, `dcb`, `dht` and `aahd` keep more fine detail. |
| `highlight_mode` | `clip` \| `ignore` \| `blend` \| `reconstruct` | `blend` | What to do where the sensor clipped (blown highlights). `clip` cuts to white; `ignore` leaves channels unclipped (can turn magenta); `blend` fades smoothly to white; `reconstruct` rebuilds detail from unclipped channels (slower). |
| `lens_corrections` | `true` \| `false` | `false` | Apply the lens corrections a DNG carries: vignetting gain maps and distortion / colour-fringing warps (`OpcodeList3`). **Experimental**: written from the DNG specification but not yet checked against a reference render, so it is off by default. Only for DNGs that are not stored rotated. |
| `baseline_exposure` | `true` \| `false` | `true` | Apply the DNG `BaselineExposure` tag (brightening the camera's deliberate underexposure). Some cameras record the raw 2 to 4 stops dark on purpose; with this off, their photos decode that much too dark. Has no effect on originals without the tag. |

The defaults for the first two keys may change during M1 while they are tested on real photos.

### `normalise`

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | `true` \| `false` | `true` | Run the normalise stage. Off, photos keep the raw's own (darker) exposure. |
| `exposure` | mapping | see below | One brightness change per photo. |
| `chroma_nr` | mapping | see below | Colour noise reduction in the shadows: smooths colour, keeps each pixel's brightness. |

#### `normalise.exposure`

The exposure change is `offset_ev + correction × (target_ev − the photo's median brightness)`, with the correction part limited to ±`max_correction_ev`.

| Key | Type | Default | Description |
|---|---|---|---|
| `offset_ev` | number, −4 to 6 | `2.0` | Brightening applied to every photo, in stops. Cameras render about 2 stops brighter than the raw's own exposure; this value was fitted to camera JPEGs. |
| `correction` | number, 0–1 | `0.0` | How far each photo's median brightness is pulled toward `target_ev`. `0` is off (like a camera), `1` makes every photo's median equal. |
| `target_ev` | number, −6 to 3 | `-1.0` | The median brightness `correction` pulls toward, in stops relative to mid grey. |
| `max_correction_ev` | number, 0–6 | `2.0` | The largest change `correction` may make, in stops. |

#### `normalise.chroma_nr`

| Key | Type | Default | Description |
|---|---|---|---|
| `amount` | number, 0–1 | `1.0` | Strength in the darkest tones. `0` turns it off. |
| `radius` | number, 0–0.05 | `0.004` | Blur radius as a fraction of the photo's long edge (`0.004` is 31 px on a 7680 px photo). |
| `full_lightness` | number, 0–1 | `0.2` | Tones up to this lightness (the cube root of luminance, after exposure; 0.2 is 4.5 stops below mid grey) get the full amount. |
| `fade_lightness` | number, 0–1 | `0.4` | By this lightness (1.5 stops below mid grey) it has faded out, so brighter areas keep crisp colour edges. Must be greater than `full_lightness`. |

### `grade`

| Key | Type | Default | Description |
|---|---|---|---|
| `local_contrast` | mapping | see below | Keeps detail (clouds, distant hills) where the display transform would flatten it. |
| `display_transform` | mapping | see below | The AgX-style display transform that turns scene light into display values, rolling highlights off toward white instead of clipping them. |

#### `grade.local_contrast`

The display transform squeezes bright and very dark tones together, and the small differences that make up detail (clouds against a bright sky, haze between hills) get squeezed with them. Local contrast splits the image into broad areas, whose brightness the display transform still decides, and the detail on top of them, which it amplifies where the curve is flat. Big sharp steps such as a horizon count as edges and are left alone, so they get no halo.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | `true` \| `false` | `true` | Run local contrast. |
| `detail_floor` | number, 0–2 | `0.8` | Least contrast detail in tones brighter than mid grey keeps after the display transform, in display stops per scene stop. The curve alone leaves about 0.2 in a bright sky; `0` turns this part off. |
| `amount` | number, 0–3 | `1.15` | Extra detail contrast everywhere. `1` adds none. |
| `radius` | number, 0–0.25 | `0.05` | Size of the broad areas, as a fraction of the photo's long edge. Anything smaller counts as detail. |
| `edge_ev` | number, 0–6 | `1.0` | Brightness steps much bigger than this many stops are treated as edges and not amplified (no halos). Lower protects more edges but keeps less detail. |
| `detail_limit_ev` | number, 0–3 | `0.25` | Detail bigger than about this many stops (a sun glint, a lamp) is amplified less, so it isn't pushed into white. Cloud texture is a few tenths of a stop. |
| `max_gain` | number, 1–10 | `4.0` | The most detail is ever amplified, as a factor. |

Defaults were fitted to camera JPEGs ([ADR-0011](decisions/0011-local-contrast.md)).

#### `grade.display_transform`

| Key | Type | Default | Description |
|---|---|---|---|
| `min_ev` | number < 0 | `-10.0` | Scene brightness, in stops relative to mid grey, that becomes black. |
| `max_ev` | number > 0 | `9.0` | Scene brightness, in stops relative to mid grey, that becomes white. Higher keeps more detail in bright skies but makes highlights greyer. |
| `contrast` | number > 0 | `1.3` | Midtone contrast. `1.0` matches a plain sRGB display of the linear image at mid grey; higher is punchier. |
| `toe` | number, 0–10 | `2.1` | How the shadows approach black: higher keeps them linear longer, then drops into black faster. |
| `shoulder` | number, 0–10 | `2.1` | How highlights approach white: lower rolls off earlier and more gently, higher keeps them bright longer, then rolls off harder. |
| `inset` | three numbers, 0–1 (R, G, B) | `[0.25, 0.25, 0.25]` | How much each primary is pulled toward white before the curve. More inset makes very bright, saturated colours fade to white with less hue shift, but desaturates. |
| `chroma_preservation` | number, 0–1 | `0.7` | Blend toward a render that tone-maps brightness only and keeps each pixel's colour ratios. `0` is pure AgX, where bright colours (a blue sky) wash out toward white much faster than in camera JPEGs; `1` keeps them fully saturated. |
| `saturation` | number, 0–3 | `1.25` | Overall colour strength after the curve. `1` changes nothing. |
| `saturation_fade` | number, 0–1 | `1.0` | How much of the `saturation` change fades out toward white. `1`: none is left at white, so bright colours don't get pushed against the edge of the gamut; `0`: the same everywhere. |
| `outset` | three numbers, 0–1 (R, G, B) | `[0.35, 0.35, 0.35]` | How much saturation each primary gets back after the curve. Larger than `inset` gives a net saturation boost in the midtones. |

Mid grey (scene `0.18`) always stays mid grey on screen, whatever these values are (`normalise.exposure.offset_ev` brightens the scene before it gets here). The defaults were fitted to camera JPEGs ([ADR-0010](decisions/0010-camera-matched-neutral-render.md)). `contrast` must be high enough for the curve to reach black at `min_ev` and white at `max_ev`; a config where it can't is rejected.

### `export`

| Key | Type | Default | Description |
|---|---|---|---|
| `outputs` | mapping of name → output | `web`, `archive` | Named export targets. Names are lowercase `snake_case` (`web`, `instagram_story`). |
| `enabled` | list of output names | `[web, archive]` | Outputs to write, in order. Each must be defined in `outputs` and listed once. |

Each output:

| Key | Type | Default | Description |
|---|---|---|---|
| `long_edge` | integer > 0, or `null` | `null` | Longest side of the exported image, in pixels. `null` keeps the original resolution. |
| `quality` | integer 1–100 | `90` | JPEG quality. |
| `sharpen` | mapping | `{amount: 0.5, radius: 0.8}` | Unsharp mask at the output's size: `amount` (0–3, `0` is off) and `radius` in output pixels (0–5). The default `archive` output uses `{amount: 0.3, radius: 1.2}`. |

Exports are written to `<project>/exports/<output name>/`.

## Validation and errors

picturesq checks the whole file before doing any work:

- **Unknown keys are errors.** A typo like `demosiac:` is reported, not silently ignored.
- **Every problem names its key and value:**

  ```
  error: picturesq.yaml is invalid (1 problem(s)):
    export.outputs.web.quality: Input should be less than or equal to 100 (got 120)
  ```
- **Exit code 2** means the config (or the command line) is invalid. See the exit codes below.

| Exit code | Meaning |
|---|---|
| `0` | Success |
| `1` | Error while running |
| `2` | Invalid config or usage |

## Notes

- **Writes are atomic.** picturesq writes to a temporary file and renames it over `picturesq.yaml`, so a crash never leaves a half-written file.
- **Comments are not preserved.** The file is rewritten by the UI and CLI, so put notes elsewhere.
- **JSON Schema:** `picturesq schema` will print a schema for editor autocompletion and agents (coming in [#13](https://github.com/eddiemg10/picturesq/issues/13)).
