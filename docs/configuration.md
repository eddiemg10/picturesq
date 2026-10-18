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

> **Status:** config format version `1`, pre-alpha. This page documents what exists today (`decode`, `normalise`, `grade.local_contrast`, `grade.display_transform`, `export`, `photos`). Sections for looks and adjustments are added as those stages ship.

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
  adjust_white_level: 0.0
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
photos: {}
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

## Reference

### Top level

| Key | Type | Default | Description |
|---|---|---|---|
| `version` | `1` | `1` | Config format version. Only `1` is accepted. |
| `decode` | mapping | see below | How RAW originals are decoded. |
| `normalise` | mapping | see below | Per-photo corrections (exposure, colour noise reduction, scene contrast) and the checks that flag photos for review. |
| `grade` | mapping | see below | How images are rendered for display. Today only the display transform. |
| `export` | mapping | see below | Which files `picturesq export` writes. |
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
| `adjust_white_level` | number, 0 to under 1 | `0.0` | When a photo's brightest raw value is above this fraction of the **white level** (the raw value the sensor reports when full), use that value as the white level instead, which brightens the whole photo. `0` never does it, so a photo's brightness doesn't depend on what's in the frame: a small lamp or reflection can't brighten everything else. LibRaw's own default is `0.75`; at that setting a 16 px spot at 80 % of the white level brightens a whole photo ×1.25 (ADR-0018). |
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

Each photo:

| Key | Type | Default | Description |
|---|---|---|---|
| `normalise` | mapping | `{}` | This photo's normalise overrides, below. |

`photos.<name>.normalise`:

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | `true` \| `false` \| `null` | `null` | Run the normalise stage for this photo; replaces `normalise.enabled`. `false` skips it (exposure, white balance and colour noise reduction), so the photo keeps the raw's own exposure; `null` follows the project. |
| `exposure_ev` | number, −6 to 10, or `null` | `null` | This photo's exposure change, in stops. It *replaces* the computed change (`offset_ev` plus any `correction`), so `2.0` is the default brightness and `2.5` is half a stop brighter. `null` uses the computed one. |
| `wb_kelvin` | number, 1667 to 25000, or `null` | `null` | Colour temperature of the light, in kelvin. The photo is re-balanced from its as-shot white to this one (in scene-linear, before exposure): a surface that was grey under this light comes out grey. Below the as-shot temperature the photo turns cooler (bluer), above it warmer. `null` keeps the as-shot temperature. |
| `scene_contrast` | number, 0–2, or `null` | `null` | This photo's scene contrast `amount`: replaces `normalise.scene_contrast.amount` and applies even when `scene_contrast` is off for the project, so `0.5` turns it on for one flat photo and `0` turns it off. It still only changes a scene narrower than `target_range_ev`. `null` follows the project. |
| `tint` | number, −150 to 150, or `null` | `null` | Tint of the light, `-1000 × Duv`: positive is magenta, negative green (Lightroom's direction; the Adobe DNG SDK's scale is three times ours). Re-balances like `wb_kelvin`: a positive tint turns the photo greener. `null` keeps the as-shot tint. |

`wb_kelvin` and `tint` together describe one white; set either alone and the other keeps its as-shot value (`picturesq` reads the as-shot white from the original's header). A photo whose original records no usable as-shot white can't be re-balanced: with either set, its export fails with an error naming it, and the other photos carry on.

Each export's sidecar records the photo's overrides under `config.photos`, so the sidecar alone says how the photo was rendered.

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
- **JSON Schema:** `picturesq schema` will print a schema for editor autocompletion and agents (coming in [#13](https://github.com/eddiemg10/picturesq/issues/13)).
