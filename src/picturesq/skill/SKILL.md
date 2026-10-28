---
name: picturesq
description: Grade RAW photos with the picturesq CLI. Use when the user wants to decode, normalise, grade or export a project folder of RAW photos, describes a look change in words ("warmer shadows", "softer highlights"), or needs the capture dates in exports corrected.
---

# picturesq

picturesq's state is `PROJECT/picturesq.yaml`. You change photos by editing it (it is machine-owned YAML: keep it valid, comments are not preserved), then render a preview to check. Never touch the originals; exports go to `PROJECT/exports/`.

The user may have the web UI open (`picturesq ui PROJECT`): it saves to the same file, and your edits appear in their browser within a second. Re-read the file before each edit, since they may have changed it.

## Workflow

1. **Inspect:** read `PROJECT/picturesq.yaml` (it may not exist: every key is optional); `picturesq normalise PROJECT --json` gives each photo's stats and flags.
2. **Know the options:** `picturesq looks --json` lists every look (`category/name`), what it does and its parameters with ranges; `picturesq schema project` is the config's JSON Schema. The full reference is https://github.com/eddiemg10/picturesq/blob/main/docs/configuration.md.
3. **Edit the config** (below), keeping values inside the documented ranges.
4. **Preview:** `picturesq preview PROJECT --look <the look> --png sheet.png` and look at the image. Each row is a photo: neutral, its **current** grade (blue border, what an export will give), then the looks asked for. An invalid edit exits 2 with the key and value named: fix it and rerun.
5. **Iterate**, then let the user make the taste call. Export with `picturesq export PROJECT`.

## Where a change goes

- The whole project: `grade.look` (`{name, intensity, parameters}`) and `grade.adjustments`.
- One photo: `photos.<FILE NAME>.grade.look` replaces the look; `photos.<FILE NAME>.grade.adjustments` replaces only the keys it sets. Intensity `0` there means no look for that photo.

## Words to edits

| The user says | Edit (project or one photo's `grade`) |
|---|---|
| warmer / cooler | `adjustments.warmth`: +10 / −10 (mired; ±25 is strong) |
| greener / more magenta | `adjustments.tint`: −5 / +5 |
| brighter / darker | `adjustments.exposure`: +0.3 / −0.3 (stops) |
| punchier / flatter, softer | `adjustments.contrast`: +0.1 / −0.1 |
| more colour / less colour | `adjustments.vibrance` +0.2 (spares skin) or `adjustments.saturation` +0.15 / −0.2 |
| black and white | `look: {name: bw/silver}` (or another `bw/` look) |
| less (or more) of the look | `look.intensity`: 0.6 / 1.2 (0 to 1.5) |
| a look's own control ("more fade", "cooler shadows") | `look.parameters.<name>` from `picturesq looks --json`, within its min and max |
| softer highlights, "the sky / screen is blown" | `adjustments.highlights`: −0.3 (−0.5 is a clear pull, −1 the most; only the bright areas move) |
| brighter highlights | `adjustments.highlights`: +0.3 |
| "like film", "moody", "cinematic" | show the category with `picturesq preview PROJECT --category <bw\|cold\|warm\|cinematic>` and let the user pick |

A worked example, with the sheet it gives, is in the configuration reference (*An agent grades a project*).

Example: "make the sunset photos warmer, and the rest nordic at 80 %":

```yaml
grade:
  look: {name: cold/nordic, intensity: 0.8}
photos:
  DJI_0042.DNG:
    grade:
      adjustments: {warmth: 15}
```

## Exposure and white balance of one photo

`picturesq normalise PROJECT --json` flags photos that need a look (too dark, too bright, clipped). Fix one in `photos.<FILE NAME>.normalise`:

- `exposure_ev`: the photo's exposure change in stops. It *replaces* the computed one (`normalise.exposure.offset_ev`, 2.0 by default), so `2.5` is half a stop brighter than the default.
- `wb_kelvin` (1667 to 25000) and `tint` (−150 to 150): the colour of the light, when the camera's white balance was wrong ("this photo is too orange": a lower `wb_kelvin` than the as-shot one turns it cooler). For a creative shift use `grade.adjustments.warmth` instead.

## Capture dates and times

Exports carry each photo's capture time; originals are never changed. Use the CLI rather than editing the keys by hand:

- `picturesq metadata show PROJECT --json`: each photo's camera time and corrected time.
- A camera whose clock was wrong (dates in 2000, an hour off): `picturesq metadata shift PROJECT --photo NAME --actual "2026-10-17 20:05"` sets `metadata.time_shift` from one photo whose real time the user knows; every photo moves by the same amount.
- `picturesq metadata zone PROJECT +01:00` sets the time zone; `picturesq metadata time PROJECT NAME "…"` sets one photo's time.
- `picturesq metadata apply PROJECT` rewrites the dates in exports already written, without re-rendering.
