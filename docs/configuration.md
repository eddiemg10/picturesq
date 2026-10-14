# Configuration

Each project folder has one config file, `picturesq.yaml`, next to the originals:

```
lisbon/
  DJI_0001.DNG
  DJI_0002.DNG
  picturesq.yaml
```

You don't need to write it: `picturesq run` creates it with defaults, and `picturesq ui` edits it for you. Coding agents can edit it directly. Every key is optional, so an empty file (or `{}`) means "all defaults".

> **Status:** config format version `1`, pre-alpha. This page documents what exists today (`decode`, `export`). Sections for normalise, grade and per-photo overrides are added as those stages ship.

## Defaults

This is the complete file with every default written out:

```yaml
version: 1
decode:
  demosaic: ahd
  highlight_mode: blend
  baseline_exposure: true
export:
  outputs:
    web:
      long_edge: 2048
      quality: 90
    archive:
      long_edge: null
      quality: 95
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

Setting `outputs` replaces the default outputs entirely, so list every output you want to keep (`archive` isn't defined above, so it can't be enabled).

## Reference

### Top level

| Key | Type | Default | Description |
|---|---|---|---|
| `version` | `1` | `1` | Config format version. Only `1` is accepted. |
| `decode` | mapping | see below | How RAW originals are decoded. |
| `export` | mapping | see below | Which files `picturesq export` writes. |

### `decode`

| Key | Type | Default | Description |
|---|---|---|---|
| `demosaic` | `linear` \| `vng` \| `ppg` \| `ahd` \| `dcb` \| `dht` \| `aahd` | `ahd` | Algorithm that reconstructs full colour from the sensor's colour-filter mosaic. `linear` is fastest and softest. `ahd`, `dcb`, `dht` and `aahd` keep more fine detail. |
| `highlight_mode` | `clip` \| `ignore` \| `blend` \| `reconstruct` | `blend` | What to do where the sensor clipped (blown highlights). `clip` cuts to white; `ignore` leaves channels unclipped (can turn magenta); `blend` fades smoothly to white; `reconstruct` rebuilds detail from unclipped channels (slower). |
| `baseline_exposure` | `true` \| `false` | `true` | Apply the DNG `BaselineExposure` tag (brightening the camera's deliberate underexposure). Some cameras record the raw 2 to 4 stops dark on purpose; with this off, their photos decode that much too dark. Has no effect on originals without the tag. |

The defaults for the first two keys may change during M1 while they are tested on real photos.

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
