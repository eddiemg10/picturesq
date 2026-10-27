# Configuration

Each project folder has one config file, `picturesq.yaml`, next to the originals:

```
lisbon/
  DJI_0001.DNG
  DJI_0002.DNG
  picturesq.yaml
```

You don't need to write it: `picturesq run` creates it with defaults, and `picturesq ui` edits it for you. Coding agents can edit it directly. Every key is optional, so an empty file (or `{}`) means "all defaults".

The machine-readable version of this page is the JSON Schema: `picturesq schema` prints it, and [`docs/schema/picturesq.schema.json`](schema/picturesq.schema.json) is a copy. Agents and editors can validate a `picturesq.yaml` against it.

Every export records the config that rendered it in its **sidecar** (`exports/<output>/<photo>.picturesq.json`); the sidecar's `config` section is a valid `picturesq.yaml`.

> **Status:** config format version `1`, pre-alpha. This page documents what exists today: `decode`, `normalise`, `grade` (look, adjustments, local contrast, display transform), `export`, `photos`, and the [look file](#look-files) format.

## Defaults

This is the complete file with every default written out:

```yaml
version: 1
decode:
  demosaic: ahd
  highlight_mode: blend
  colour_matrix: dng
  lens_corrections: false
  default_crop: true
  baseline_exposure: true
  proxy_long_edge: 2048
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
  scene_contrast:
    enabled: false
    amount: 0.5
    target_range_ev: 4.5
    max_contrast: 0.5
    pivot_percentile: 75.0
    soft_limit_ev: 3.0
  white_balance:
    flag_disagreement: false
    flag_disagreement_mired: 30.0
  outliers:
    min_median_ev: -2.0
    max_median_ev: 3.0
    max_clipped: 0.02
grade:
  look: null
  adjustments:
    exposure: 0.0
    highlights: 0.0
    warmth: 0.0
    tint: 0.0
    contrast: 0.0
    saturation: 0.0
    vibrance: 0.0
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
    saturation: 1.15
    saturation_fade: 0.7
    outset:
    - 0.35
    - 0.35
    - 0.35
    blue_rendering:
      enabled: true
      hue: 250.0
      hue_width: 70.0
      hue_shift: -4.0
      chroma: 1.3
      lightness: 0.94
      chroma_start: 0.01
      chroma_full: 0.05
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
metadata:
  time_shift: +0d 00:00:00
  time_zone: null
photos: {}
```

## Examples

Grade every photo with a look at 80 %, a little warmer, and one photo with another look:

```yaml
grade:
  look: {name: cold/nordic, intensity: 0.8, parameters: {fade: 0.06}}
  adjustments: {warmth: 8}
photos:
  DJI_0042.DNG:
    grade:
      look: {name: bw/silver, intensity: 1.0}
      adjustments: {exposure: 0.3}
```

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

Colorimetric skies: turn off the camera-matched blue rendering (blues stay as accurate as the colour matrix makes them, paler and a little more purple than a camera JPEG):

```yaml
grade:
  display_transform:
    blue_rendering: {enabled: false}
```

A punchier, more saturated neutral render:

```yaml
grade:
  display_transform: {contrast: 1.5, saturation: 1.4}
```

Pull every photo in a batch toward the same brightness (cameras don't do this; it is off by default, and it flattens the mood of dark and bright scenes). `target_ev: -1.0` puts the medians around `offset_ev + target_ev` = +1 stop:

```yaml
normalise:
  exposure: {correction: 0.6, target_ev: -1.0}
```

Give flat scenes (overcast, fog, snow) extra contrast, as cameras do (off by default):

```yaml
normalise:
  scene_contrast: {enabled: true}
```

No sharpening on the web output:

```yaml
export:
  outputs:
    web: {long_edge: 2048, quality: 90, sharpen: {amount: 0}}
    archive: {long_edge: null, quality: 95}
```

Setting `outputs` replaces the default outputs entirely, so list every output you want to keep (`archive` isn't defined above, so it can't be enabled).

Give one photo more light than the rest (it replaces the computed exposure, normally `offset_ev`, 2.0):

```yaml
photos:
  DJI_20261011_0042.DNG:
    normalise: {exposure_ev: 2.7}
```

Fix a camera whose clock said 2000-07-07 when it was really 2026-10-17, and give one photo its exact time:

```yaml
metadata:
  time_shift: +9598d 10:05:00
  time_zone: +01:00
photos:
  DJI_20261017_0042.DNG:
    metadata: {capture_time: '2026-10-17T20:05:00'}
```

## Reference

### Top level

| Key | Type | Default | Description |
|---|---|---|---|
| `version` | `1` | `1` | Config format version. Only `1` is accepted. |
| `decode` | mapping | see below | How RAW originals are decoded. |
| `normalise` | mapping | see below | Per-photo corrections (exposure, colour noise reduction, scene contrast) and the checks that flag photos for review. |
| `grade` | mapping | see below | How images are rendered for display. Today only the display transform. |
| `export` | mapping | see below | Which files `picturesq export` writes. |
| `metadata` | mapping | see below | Corrections to the dates and times written into exports. |
| `photos` | mapping of file name → overrides | `{}` | Per-photo overrides. See [`photos`](#photos). |

### `decode`

| Key | Type | Default | Description |
|---|---|---|---|
| `demosaic` | `linear` \| `vng` \| `ppg` \| `ahd` \| `dcb` \| `dht` \| `aahd` | `ahd` | Algorithm that reconstructs full colour from the sensor's colour-filter mosaic. `linear` is fastest and softest. `ahd`, `dcb`, `dht` and `aahd` keep more fine detail. |
| `highlight_mode` | `clip` \| `ignore` \| `blend` \| `reconstruct` | `blend` | What to do where the sensor clipped (blown highlights). `clip` cuts to white; `ignore` leaves channels unclipped (can turn magenta); `blend` fades smoothly to white; `reconstruct` rebuilds detail from unclipped channels (slower). |
| `colour_matrix` | `dng` \| `libraw` | `dng` | How camera colour becomes real colour. `dng`: as the DNG specification says, blending the file's two colour matrices (tungsten and daylight) by the photo's white balance; a tungsten-lit room gets mostly the tungsten matrix ([ADR-0012](decisions/0012-sky-colour.md)). `libraw`: LibRaw's matrix, which is always the daylight one. RAWs that aren't DNGs always use LibRaw's. |
| `lens_corrections` | `true` \| `false` | `false` | Apply the lens corrections a DNG carries: vignetting gain maps and distortion / colour-fringing warps (`OpcodeList3`). **Experimental**: written from the DNG specification but not yet checked against a reference render, so it is off by default. Only for DNGs that are not stored rotated. |
| `default_crop` | `true` \| `false` | `true` | Crop to the photo's frame as the original specifies it: the DNG `DefaultCrop` or the maker's equivalent (LibRaw reads both). Drops a few pixels of sensor border on most cameras, and the strips outside the aspect ratio the camera was set to (a Pentax Q7 set to 3:2 records the whole 4:3 sensor; with this on you get the 3:2 photo, like the camera's JPEG). |
| `baseline_exposure` | `true` \| `false` | `true` | Apply the DNG `BaselineExposure` tag (brightening the camera's deliberate underexposure). Some cameras record the raw 2 to 4 stops dark on purpose; with this off, their photos decode that much too dark. Has no effect on originals without the tag. |
| `proxy_long_edge` | integer, 256–8192 | `2048` | Long edge in pixels of the **proxy**, the small cached copy of each photo that previews and the UI work on (`.picturesq/proxies/`). Exports always use the full-resolution original. Proxies are never larger than the half-size decode they come from. Changing this, any other `decode` key, the original or the picturesq version rebuilds the proxy. |

The defaults for the first two keys may change during M1 while they are tested on real photos.

### `normalise`

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | `true` \| `false` | `true` | Run the normalise stage. Off, photos keep the raw's own (darker) exposure. |
| `exposure` | mapping | see below | One brightness change per photo. |
| `chroma_nr` | mapping | see below | Colour noise reduction in the shadows: smooths colour, keeps each pixel's brightness. |
| `scene_contrast` | mapping | see below | Extra contrast for flat scenes, as cameras add. Off by default. |
| `white_balance` | mapping | see below | When the white balance check flags a photo. |
| `outliers` | mapping | see below | The ranges a photo's stats should fall in; outside one, the photo is flagged as an outlier. |

#### `normalise.exposure`

The exposure change is `offset_ev + correction × (target_ev − the photo's median brightness)`, with the correction part limited to ±`max_correction_ev`. The median is measured on the decoded photo, before `offset_ev`, so with `correction` 1 every photo's median ends at `offset_ev + target_ev` (+1 stop by default).

| Key | Type | Default | Description |
|---|---|---|---|
| `offset_ev` | number, −4 to 6 | `2.0` | Brightening applied to every photo, in stops. Cameras render about 2 stops brighter than the raw's own exposure; this value was fitted to camera JPEGs. |
| `correction` | number, 0–1 | `0.0` | How far each photo's median brightness is pulled toward `target_ev`. `0` is off (like a camera), `1` makes every photo's median equal. |
| `target_ev` | number, −6 to 3 | `-1.0` | The median brightness `correction` pulls toward, in stops relative to mid grey, measured before `offset_ev`: with `correction` 1 the median ends at `offset_ev + target_ev`. |
| `max_correction_ev` | number, 0–6 | `2.0` | The largest change `correction` may make, in stops. |

#### `normalise.chroma_nr`

| Key | Type | Default | Description |
|---|---|---|---|
| `amount` | number, 0–1 | `1.0` | Strength in the darkest tones. `0` turns it off. |
| `radius` | number, 0–0.05 | `0.004` | Blur radius as a fraction of the photo's long edge (`0.004` is 31 px on a 7680 px photo). |
| `full_lightness` | number, 0–1 | `0.2` | Tones up to this lightness (the cube root of luminance, after exposure; 0.2 is 4.5 stops below mid grey) get the full amount. |
| `fade_lightness` | number, 0–1 | `0.4` | By this lightness (1.5 stops below mid grey) it has faded out, so brighter areas keep crisp colour edges. Must be greater than `full_lightness`. |

#### `normalise.scene_contrast`

Cameras give flat scenes (overcast light, fog, a low-contrast subject) more contrast than a fixed tone curve would. Scene contrast does the same: it measures the scene's **range**, the spread of its luminance between the 5th and 95th percentiles in stops, and a scene narrower than `target_range_ev` gets extra contrast

`amount × min(target_range_ev ÷ range − 1, max_contrast)`

Scenes at least `target_range_ev` wide are left exactly as they were. The extra contrast pushes tones away from a pivot, the `pivot_percentile` of the scene's luminance: darker tones get darker and brighter ones brighter. Near the pivot the tones get steeper by the extra contrast (`0.25` is 25 % steeper); far from it the change levels off at `soft_limit_ev × extra contrast` stops. Each pixel's red, green and blue are multiplied by the same factor, so colours keep their hue and saturation and greys stay grey. It runs in scene-linear after exposure and colour noise reduction. `picturesq normalise` records each photo's range, pivot and extra contrast in its stats (`scene_contrast`) and shows the extra contrast when it is above 0.

**Off by default.** On the two flat photos in the reference set (ranges 1.8 and 3.3 stops, both from a DJI Pocket 4) the camera JPEG's tones were 1.4–1.5× steeper than ours; on wider scenes there was no such pattern. Two photos from one camera aren't enough to change every photo, so it waits for more flat photos ([ADR-0017](decisions/0017-scene-contrast.md)). `amount: 1.0` matched the camera on those two; the default `0.5` is the gentler version preferred on review. Turn it on for the project, or for one photo with the `scene_contrast` override in [`photos`](#photos).

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | `true` \| `false` | `false` | Add contrast to flat scenes. A photo's `scene_contrast` override applies even when this is off. |
| `amount` | number, 0–2 | `0.5` | How much of the extra contrast to apply: `0.5` is gentle, `1.0` matched the camera on the photos it was fitted to, `0` turns it off. |
| `target_range_ev` | number, 0–20 | `4.5` | Scenes whose range (5th to 95th percentile of luminance) is narrower than this, in stops, get extra contrast. Raising it reaches wider scenes too: at 7, a wide-range photo's clipped highlights nearly doubled. |
| `max_contrast` | number, 0–2 | `0.5` | The most extra contrast a very flat scene gets, before `amount`: `0.5` makes tones near the pivot 50 % steeper. With the defaults a scene of 3 stops or less reaches it. |
| `pivot_percentile` | number, 0–100 | `75.0` | Tones at this percentile of the scene's luminance stay where they are. `75` keeps the bright end in place and darkens the rest, as the camera did; `50` would also brighten the bright end. |
| `soft_limit_ev` | number, 0–10 | `3.0` | Tones far from the pivot move at most this × the extra contrast, in stops, so deep shadows and highlights aren't pushed without limit. |

#### `normalise.white_balance`

Normalise keeps the white balance the camera recorded (as-shot). It also checks it: two **white balance estimates** guess the light's colour from the photo itself, `brightest` (the colour of the brightest unclipped pixels) and `grey` (the average of the nearly neutral pixels). Each is often wrong on its own (a yellow wall is bright, a sandy beach is nearly neutral), so with `flag_disagreement` on, the photo gets the `wb_disagreement` flag only when **both** differ from the as-shot white balance by at least `flag_disagreement_mired`, **in the same direction** (both warmer or both cooler). Nothing changes automatically.

The flag is **off by default**. The check still runs and its numbers are in each photo's stats, but genuinely coloured scenes trip it while the as-shot white balance is right: on the reference set it flagged 3 of 17 photos and none were wrong, all genuinely coloured scenes (ADR-0016: the camera always keeps its recorded white balance). Turn it on if you want the alarm anyway.

Why 30: on the CC0 samples and the reference set, the white balance the camera's own JPEG implies was within 15 mired of as-shot on every photo, while each estimator alone was 30 mired or more off on some of them (median errors 16–17 mired). With both required, 30 flags only the Sony FX3 sample (both estimates about 88 mired warmer). The Pentax K-5 IIs tungsten interior comes close (28 and 33 mired warmer: cameras leave tungsten light a little warm on purpose) but isn't flagged.

| Key | Type | Default | Description |
|---|---|---|---|
| `flag_disagreement` | `true` \| `false` | `false` | Raise `wb_disagreement` when the estimates disagree with as-shot. Off by default because coloured scenes such as sunsets trip it. |
| `flag_disagreement_mired` | number, 0–500 | `30.0` | How far (in mired, 10⁶ ÷ kelvin) both estimates must be from the as-shot white balance, on the same side, for the photo to be flagged. 30 mired is about 600 K near 4500 K, or 1100 K near 6500 K. |

#### `normalise.outliers`

After normalise, a photo whose stats fall outside these ranges is flagged as an **outlier**. Outliers are flagged, never forced into range: fix one with an override in [`photos`](#photos). The defaults flag only photos far from the CC0 samples and the reference set, whose medians span −2.5 to +2.3 stops.

| Key | Type | Default | Description |
|---|---|---|---|
| `min_median_ev` | number, −10 to 10 | `-2.0` | Darkest median brightness that isn't an outlier, in stops relative to mid grey. |
| `max_median_ev` | number, −10 to 10 | `3.0` | Brightest median brightness that isn't an outlier. Must be greater than `min_median_ev`. |
| `max_clipped` | number, 0–1 | `0.02` | Largest fraction of pixels the sensor clipped (pure white, no detail) that isn't an outlier. |

### `grade`

| Key | Type | Default | Description |
|---|---|---|---|
| `look` | mapping or `null` | `null` | The project's look, below; `null` is the neutral render. |
| `adjustments` | mapping | all `0` | Controls every look has, below. |
| `local_contrast` | mapping | see below | Keeps detail (clouds, distant hills) where the display transform would flatten it. |
| `display_transform` | mapping | see below | The AgX-style display transform that turns scene light into display values, rolling highlights off toward white instead of clipping them. |

#### `grade.look`

Which look the photos are graded with (see [Look files](#look-files); `picturesq looks` lists them). Its scene operations run before local contrast and the display transform, its display operations (`fade`, `grain`) after it, for each output.

| Key | Type | Default | Description |
|---|---|---|---|
| `name` | `category/name` | (required) | The look, e.g. `cold/nordic`. An unknown name is an error (exit 2) before anything is rendered. |
| `intensity` | number, 0–1.5 | `1.0` | How strongly the look applies: `0` is exactly the neutral render, `1` the look as designed, `1.5` half as much again. It scales each operation's strength, not a blend of two images ([ADR-0019](decisions/0019-grade-operations-and-intensity.md)). |
| `parameters` | mapping of name to number | `{}` | Values for the look's parameters (its sliders); unset ones use the look's defaults. An unknown name or a value outside the parameter's range is an error. |

#### `grade.adjustments`

The same seven controls for every look, applied after the look's scene operations and before local contrast, so "a bit warmer" means the same on every look. All `0` changes nothing.

| Key | Type | Default | Description |
|---|---|---|---|
| `exposure` | number, −3–3 | `0.0` | Exposure change in stops. |
| `highlights` | number, −1–1 | `0.0` | The bright areas only (an LED screen, a window): negative darkens them and keeps their detail, positive brightens them. Mid tones and shadows don't change. It is the `highlights` operation with its defaults; `-0.5` is a clear pull, `-1` the most. |
| `warmth` | number, −50–50 | `0.0` | Warmth in mired: positive is warmer (yellower), negative cooler. 10 is a gentle change. |
| `tint` | number, −30–30 | `0.0` | Positive is magenta, negative green. |
| `contrast` | number, −0.5–0.5 | `0.0` | Contrast around mid grey, in stops: `0.1` makes every stop 1.1 stops. Colours keep their hue and saturation. |
| `saturation` | number, −1–1 | `0.0` | Colour for every colour, lightness kept: `-1` is black and white. |
| `vibrance` | number, −1–1 | `0.0` | Colour for muted colours, less for vivid ones (skin changes less than with `saturation`). |

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
| `saturation` | number, 0–3 | `1.15` | Overall colour strength after the curve. `1` changes nothing. |
| `saturation_fade` | number, 0–1 | `0.7` | How much of the `saturation` change fades out toward white. `1`: none is left at white, so bright colours don't get pushed against the edge of the gamut; `0`: the same everywhere. |
| `outset` | three numbers, 0–1 (R, G, B) | `[0.35, 0.35, 0.35]` | How much saturation each primary gets back after the curve. Larger than `inset` gives a net saturation boost in the midtones. |
| `blue_rendering` | mapping | see below | Camera-matched skies: blues rendered deeper, more colourful and slightly cyan, as camera JPEGs do. On by default; `enabled: false` turns it off. |

Mid grey (scene `0.18`) always stays mid grey on screen, whatever these values are (`normalise.exposure.offset_ev` brightens the scene before it gets here). The defaults were fitted to camera JPEGs ([ADR-0010](decisions/0010-camera-matched-neutral-render.md)). `contrast` must be high enough for the curve to reach black at `min_ev` and white at `max_ev`; a config where it can't is rejected.

#### `grade.display_transform.blue_rendering`

Camera JPEGs don't render blue skies accurately: they make them deeper, more colourful and a few degrees more cyan, because that's how people remember a blue sky. Measured against the DJI Pocket 4's and a DJI drone's JPEGs, an accurate render is ~1.2–1.6× less colourful in the sky, a little lighter and ~4° more purple. This step reproduces the camera's sky. It touches only blues: greys, whites and every other hue are left exactly as they were. The defaults are fitted to DJI JPEGs ([ADR-0012](decisions/0012-sky-colour.md)); other makers do less of this (Fujifilm's skies are close to accurate), so it is the one place the neutral render leans toward DJI's look.

**To turn it off**, set `enabled: false` (see the example above). Blues then come out exactly as the colour matrix and the display transform make them. Setting `hue_shift: 0`, `chroma: 1` and `lightness: 1` has the same effect.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | `true` \| `false` | `true` | Apply the camera-matched blue rendering. `false`: colorimetric blues. |
| `hue` | number, 0–360 | `250.0` | Centre of the affected hues, as an Oklab hue angle in degrees (sky blue is ~230–270). |
| `hue_width` | number, 0–120 | `70.0` | Hues this many degrees or more from `hue` are untouched; the effect fades smoothly (raised cosine) between. |
| `hue_shift` | number, −30–30 | `-4.0` | Hue rotation at the centre, in degrees. Negative turns blue toward cyan, positive toward purple. |
| `chroma` | number, 0.5–2 | `1.3` | Colourfulness scale at the centre. `1` changes nothing. |
| `lightness` | number, 0.5–1.5 | `0.94` | Lightness scale at the centre. Below `1` darkens (a deeper sky). |
| `chroma_start` | number, 0–0.2 | `0.01` | Oklab chroma below which pixels are untouched, so greys and whites keep their exact colour. |
| `chroma_full` | number, 0–0.4 | `0.05` | Oklab chroma from which the full adjustment applies. Must be greater than `chroma_start`. |

Colours the step pushes outside what the display can show are brought back in at constant hue and lightness (Oklab gamut fit), so deep blues don't drift toward purple.

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

### `metadata`

A camera whose clock was never set (a DJI Pocket 4 after a battery reset says 2000-07-07) stamps every photo with a wrong date, and photo libraries and social apps sort by it. Originals are never changed, so the correction lives here and is written into the exports' EXIF: `DateTimeOriginal`, `DateTimeDigitized` and `DateTime`, plus `OffsetTime`, `OffsetTimeOriginal` and `OffsetTimeDigitized` when `time_zone` is set. With the defaults nothing changes. Each export's sidecar records the camera's time and the corrected one under `metadata`.

| Key | Type | Default | Description |
|---|---|---|---|
| `time_shift` | text | `+0d 00:00:00` | Added to every photo's capture time. A sign, then days (`9598d`), then `HH:MM:SS`, exact to the second: `+9598d 10:05:00` moves a photo from 2000-07-07 to 2026-10-17 (the same sign convention as a clock correction: positive is later). Easiest to set with `picturesq metadata shift --photo NAME --actual "2026-10-17 20:05"`, which works it out from one photo whose real time you know. |
| `time_zone` | `±HH:MM` or `null` | `null` | The zone the corrected times are in, as an offset from UTC (`+01:00`), written as the `OffsetTime*` tags. EXIF times carry no zone of their own. `null` leaves the camera's offset tags alone. |

```yaml
metadata:
  time_shift: +9598d 10:05:00
  time_zone: +01:00
```

A photo whose original records no capture time is not shifted (there is nothing to shift); give it one with `photos.<name>.metadata.capture_time`. A shift is at the project level because a wrong clock is wrong by the same amount for every photo until someone resets it; if the camera was reset part way through, use the per-photo capture time for the other photos.

`picturesq metadata` edits these settings and can rewrite exports already on disk: see the [project plan](project-plan.md#7-cli-specification).

### `photos`

Per-photo **overrides**, written by the UI (or an agent) when one photo needs something different from the project's settings. Keys are the original's file name (`DJI_0042.DNG`), matched ignoring case; a photo with no entry uses the project's settings. An entry for a file that isn't in the project is kept (it may be added later).

```yaml
photos:
  DJI_0042.DNG:
    normalise: {exposure_ev: 2.7}
  DJI_0043.DNG:
    normalise: {wb_kelvin: 3200}   # lit by tungsten; the camera balanced for daylight
  DJI_0044.DNG:
    normalise: {enabled: false}    # skip normalise for this photo
  DJI_0045.DNG:
    normalise: {scene_contrast: 0.5}   # a foggy scene: extra contrast for this photo only
```

The UI writes only what a photo overrides: unset values are left out, and a photo whose last override is removed disappears from `photos`.

Each photo:

| Key | Type | Default | Description |
|---|---|---|---|
| `normalise` | mapping | `{}` | This photo's normalise overrides, below. |
| `grade` | mapping | `{}` | This photo's look and adjustments, below. |
| `metadata` | mapping | `{}` | This photo's capture time, below. |

`photos.<name>.normalise`:

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | `true` \| `false` \| `null` | `null` | Run the normalise stage for this photo; replaces `normalise.enabled`. `false` skips it (exposure, white balance and colour noise reduction), so the photo keeps the raw's own exposure; `null` follows the project. |
| `exposure_ev` | number, −6 to 10, or `null` | `null` | This photo's exposure change, in stops. It *replaces* the computed change (`offset_ev` plus any `correction`), so `2.0` is the default brightness and `2.5` is half a stop brighter. `null` uses the computed one. |
| `wb_kelvin` | number, 1667 to 25000, or `null` | `null` | Colour temperature of the light, in kelvin. The photo is re-balanced from its as-shot white to this one (in scene-linear, before exposure): a surface that was grey under this light comes out grey. Below the as-shot temperature the photo turns cooler (bluer), above it warmer. `null` keeps the as-shot temperature. |
| `scene_contrast` | number, 0–2, or `null` | `null` | This photo's scene contrast `amount`: replaces `normalise.scene_contrast.amount` and applies even when `scene_contrast` is off for the project, so `0.5` turns it on for one flat photo and `0` turns it off. It still only changes a scene narrower than `target_range_ev`. `null` follows the project. |
| `tint` | number, −150 to 150, or `null` | `null` | Tint of the light, `-1000 × Duv`: positive is magenta, negative green (Lightroom's direction; the Adobe DNG SDK's scale is three times ours). Re-balances like `wb_kelvin`: a positive tint turns the photo greener. `null` keeps the as-shot tint. |

`wb_kelvin` and `tint` together describe one white; set either alone and the other keeps its as-shot value (`picturesq` reads the as-shot white from the original's header). A photo whose original records no usable as-shot white can't be re-balanced: with either set, its export fails with an error naming it, and the other photos carry on.

`photos.<name>.grade`:

| Key | Type | Default | Description |
|---|---|---|---|
| `look` | mapping or `null` | `null` | Replaces the project's `grade.look` for this photo (name, intensity and parameters together; see `grade.look`). Intensity `0` grades this photo with no look. `null` follows the project. |
| `adjustments` | mapping | `{}` | This photo's adjustments: each key set (`exposure`, `highlights`, `warmth`, `tint`, `contrast`, `saturation`, `vibrance`, same ranges as `grade.adjustments`) replaces the project's value; unset (`null`) ones follow the project. |

`photos.<name>.metadata`:

| Key | Type | Default | Description |
|---|---|---|---|
| `capture_time` | date and time, or `null` | `null` | When this photo was taken, as the camera's clock should have shown it: `2026-10-17T20:05:00` (a space instead of the `T` also works; no zone, see `metadata.time_zone`). It *replaces* the camera's time and wins over `metadata.time_shift`. `null` follows the project. |

Each export's sidecar records the photo's overrides under `config.photos` (those that change the picture; the capture time is recorded under `metadata`), and the look it was graded with under `look` (name, intensity, every parameter's value and the look file's SHA-256), so the sidecar alone says how the photo was rendered.

## Look files

A **look** (e.g. `cold/nordic`) is defined by a **look file**: YAML with the look's metadata, the **parameters** it shows in the UI, and the **operations** it applies, in order. The built-in ones are in `src/picturesq/grade/looks/<category>/<name>.yaml`. `picturesq schema look` prints the look file's JSON Schema; [`docs/schema/look.schema.json`](schema/look.schema.json) is a copy.

```yaml
version: 1
name: nordic
category: cold                   # bw | cold | warm | cinematic
description: Muted, cool shadows, clean whites, lifted blacks
parameters:
  shadow_tint: {default: 0.3, min: 0.0, max: 0.8, label: Shadow tint}
  fade: {default: 0.04, min: 0.0, max: 0.12, label: Fade}
operations:
  - {op: white_balance, warmth: -12}
  - {op: contrast, amount: 0.12}
  - {op: split_tone, shadows: {hue: 230, amount: $shadow_tint}, highlights: {hue: 70, amount: 0.1}}
  - {op: saturation, amount: -0.15}
  - {op: fade, amount: $fade}
```

| Key | Type | Description |
|---|---|---|
| `version` | `1` | Look file format version. |
| `name` | name | The look's name within its category; must match the file name. |
| `category` | `bw` \| `cold` \| `warm` \| `cinematic` | Must match the folder. Projects refer to the look as `category/name`. |
| `description` | text, up to 200 characters | One line, for people. |
| `parameters` | mapping of name to parameter | Values the UI shows as sliders. Each has `default`, `min`, `max` (`min ≤ default ≤ max`) and `label`. |
| `operations` | list, 1–32 | The steps, in order. Any number in an operation can be a **parameter reference** `$name` instead. |

**Validation:** every `$name` must be a parameter, every parameter must be used, and every operation must be valid with all its parameters at their default, at their `min` and at their `max`. Unknown keys and unknown `op` names are errors, as in `picturesq.yaml`.

**Intensity** (how strongly a look applies, 0–150 %) scales each operation's strength values between their **neutral value** (where the operation does nothing) and the look's value; values that say where or which (a pivot, a hue) are kept. So `exposure: {ev: 1}` at 50 % is +0.5 EV, and at 0 % every operation is skipped: exactly the neutral render ([ADR-0019](decisions/0019-grade-operations-and-intensity.md)). Below, the strength values are those with a neutral value.

**Order:** the look's scene operations run on scene light, then adjustments, then local contrast and the display transform; the look's display operations run after the display transform, for each output (`fade`, `grain`, `lut`).

### Operations

#### `exposure` (scene)

| Key | Type | Neutral | Description |
|---|---|---|---|
| `ev` | number, −4–4 | `0` | Exposure change in stops: `1` doubles the light. |

#### `white_balance` (scene)

| Key | Type | Neutral | Description |
|---|---|---|---|
| `warmth` | number, −100–100 | `0` | Warmth in mired; positive is warmer (yellower), negative cooler. 10–20 is a gentle change. |
| `tint` | number, −50–50 | `0` | Tint on the same scale as `photos.<name>.normalise.tint`; positive is magenta, negative green. |

#### `contrast` (scene)

| Key | Type | Neutral | Description |
|---|---|---|---|
| `amount` | number, −0.9–1 | `0` | Extra contrast around `pivot`, in stops: `0.2` makes every stop away from it 1.2 stops. The same gain on R, G and B, so colours keep their hue and saturation. |
| `pivot` | number, 0–1 | — | Scene luminance that stays put. Default `0.18` (mid grey). |

#### `saturation` (scene)

| Key | Type | Neutral | Description |
|---|---|---|---|
| `amount` | number, −1–1 | `0` | Chroma change for every colour, lightness and hue kept: `-1` is black and white, `0.2` is 20 % more colour. |

#### `vibrance` (scene)

| Key | Type | Neutral | Description |
|---|---|---|---|
| `amount` | number, −1–1 | `0` | Chroma change for muted colours, fading to none for colourful ones (Oklab chroma 0.25 and up), so skin and vivid colours change less than with `saturation`. |

#### `tone_curve` (scene)

| Key | Type | Neutral | Description |
|---|---|---|---|
| `points` | list of `[input, output]`, up to 16 | each output = its input | Brightness in stops relative to mid grey: `[2, 1.5]` moves what was 2 stops above mid grey to 1.5 stops (softer highlights). Inputs must increase, outputs must not decrease, all within ±12. The curve is smooth and never overshoots; beyond the first and last points it continues straight at the slope between the two end points, so softened highlights stay soft. Colours keep their hue and saturation. Intensity moves each output toward its input. |

#### `hsl` (scene)

Changes colours by **hue band**: `red`, `orange` (skin), `yellow`, `green`, `aqua`, `blue` (sky), `purple`, `magenta`. Neighbouring bands blend smoothly, and greys aren't changed. Each band is a mapping:

| Key | Type | Neutral | Description |
|---|---|---|---|
| `hue` | number, −45–45 | `0` | Hue shift in degrees: positive turns red toward yellow, blue toward purple. |
| `chroma` | number, −1–1 | `0` | Chroma change; `-1` removes the band's colour. |
| `lightness` | number, −2–2 | `0` | Brightness change in stops (a darker sky: `-0.5`). |

| Key | Type | Description |
|---|---|---|
| `red` | band | Reds (Oklab hue around 25°). |
| `orange` | band | Oranges and skin (55°). |
| `yellow` | band | Yellows (100°). |
| `green` | band | Greens and foliage (140°). |
| `aqua` | band | Cyans (195°). |
| `blue` | band | Blues and sky (255°). |
| `purple` | band | Purples (295°). |
| `magenta` | band | Magentas (330°). |

#### `split_tone` (scene)

Tints the shadows toward one hue and the highlights toward another, lightness kept; black stays black.

| Key | Type | Neutral | Description |
|---|---|---|---|
| `shadows` | `{hue, amount}` | `amount: 0` | `hue`: 0–360 (Oklab hue: about 25 red, 55 orange, 100 yellow, 140 green, 195 cyan, 255 blue). `amount`: 0–1; `1` adds a strong tint (0.1 Oklab chroma at mid grey). |
| `highlights` | `{hue, amount}` | `amount: 0` | The same, for the highlights. |
| `balance` | number, −1–1 | — | Where shadows end and highlights start: positive gives the shadows' tint more of the tones. Default `0` (mid grey). |

#### `channel_mixer` (scene)

Black and white from a mix of R, G and B.

| Key | Type | Neutral | Description |
|---|---|---|---|
| `red` | number, −1–2 | — | Red weight. Default `0.2627`. More red darkens blue skies and lightens skin (a red filter). |
| `green` | number, −1–2 | — | Green weight. Default `0.678`. |
| `blue` | number, −1–2 | — | Blue weight. Default `0.0593`. The weights are divided by their sum (at least 0.1), so greys stay the same grey. |
| `amount` | number, 0–1 | `0` | How far toward black and white; `1` is fully grey. |

#### `vignette` (scene)

| Key | Type | Neutral | Description |
|---|---|---|---|
| `amount` | number, −3–1 | `0` | Change at the corners in stops; negative darkens. |
| `midpoint` | number, 0–1 | — | Where it starts, as a distance from the centre (corners are 1). Default `0.5`. |
| `roundness` | number, 0–1 | — | `1` is a circle, `0` an ellipse with the frame's shape. Default `1`. |

#### `highlights` (scene)

Darkens (or brightens) the bright areas only, keeping their detail. Brightness is judged on a smooth version of the photo (an edge-aware blur), so a whole LED screen counts as one bright area and the text on it stays readable detail. Below `start_ev` nothing changes; above it, each stop of that smooth brightness becomes `1 + 0.8 × amount` stops, easing in over the first 1.5 stops; R, G and B get the same gain, so colours keep their hue.

| Key | Type | Neutral | Description |
|---|---|---|---|
| `amount` | number, −1–1 | `0` | Negative darkens the bright areas, positive brightens them. At `-1` each stop above the start becomes 0.2 stops. |
| `start_ev` | number, −1–6 | — | Where it starts, in stops above mid grey (of the smooth brightness); nothing below it changes. Default `1.5`. |
| `radius` | number, 0–0.25 | — | Size of the areas brightness is judged over, as a fraction of the long edge. Default `0.06`. Smaller follows small lights more closely but flattens detail inside them. |

#### `fade` (display)

| Key | Type | Neutral | Description |
|---|---|---|---|
| `amount` | number, 0–0.3 | `0` | Lifts black to this sRGB value (`0.05` is 13 of 255), white stays white: the matte look of faded film. |

#### `grain` (display)

Film-like grain, the same on every run and the same pattern in every output.

| Key | Type | Neutral | Description |
|---|---|---|---|
| `amount` | number, 0–0.1 | `0` | Strength in the mid tones, as an sRGB value; it fades out toward black and white. `0.02` is subtle. |
| `size` | number, 0.0002–0.005 | — | Grain size as a fraction of the long edge. Default `0.0005` (1/2000). |

#### `lut` (display)

A 3D (or 1D) LUT in a `.cube` file, applied after the display transform. A LUT only means something in the colour space it was made for, so the operation says which. Ship the `.cube` next to the look file; its bytes are part of the look's hash in each sidecar.

| Key | Type | Neutral | Description |
|---|---|---|---|
| `file` | path ending `.cube` | — | Relative to the look file's folder, e.g. `luts/filmic.cube`; no `..`. Read when the look loads: a missing or malformed file is an error naming it (and the line). |
| `input_space` | `srgb` \| `rec709` | — | What the LUT expects and returns: `srgb` (sRGB primaries and curve; most creative LUTs) or `rec709` (Rec.709 primaries, gamma 2.4). Default `srgb`. |
| `amount` | number, 0–1 | `0` | Blend of the LUT's result with its input. Default `1` (the LUT as made); intensity scales it like any strength value. |

Values between the LUT's grid points are interpolated **tetrahedrally**, which keeps greys grey if the LUT does ([learning log](learning-log.md)).

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
| `3` | Completed, but a photo has a flag (only `picturesq normalise --strict`) |

## Notes

- **Writes are atomic.** picturesq writes to a temporary file and renames it over `picturesq.yaml`, so a crash never leaves a half-written file.
- **Comments are not preserved.** The file is rewritten by the UI and CLI, so put notes elsewhere.
- **JSON Schema:** `picturesq schema` prints the schema of `picturesq.yaml` and `picturesq schema look` that of a look file, for editor autocompletion and agents.
