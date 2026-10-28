# picturesq

Turn a folder of RAW photos into consistently graded exports. No photo editor needed.

```bash
picturesq run ./lisbon    # decode → normalise → grade → export
picturesq ui ./lisbon     # choose looks, fix exposure and dates, export, in a local web UI
```

- Any camera LibRaw supports; built and tested on DJI Osmo Pocket DNGs
- Runs on an 8 GB, CPU-only laptop (Linux, WSL2, Windows)
- 18 built-in looks in four categories (B/W · Cold · Warm · Cinematic), each with adjustable intensity
- Each photo is normalised first (exposure, colour noise), so one look gives a consistent result across a whole shoot
- Everything you choose is saved in one YAML file, `picturesq.yaml`, which a coding agent can edit too
- Your originals are never changed: exports go to `<project>/exports/`

**Status:** alpha (v0.1). Feedback and bug reports are welcome on [GitHub issues](https://github.com/eddiemg10/picturesq/issues).

## Install

Python 3.11 or newer. With [uv](https://docs.astral.sh/uv/) (or `pipx install picturesq`):

```bash
uv tool install picturesq
picturesq doctor          # checks the libraries, CPU and memory picturesq will use
```

## Quick start

A **project** is a folder of RAW files. Point picturesq at it:

```bash
picturesq ui ./lisbon
```

The browser opens with your photos. Pick a look for the whole project or one photo, set its intensity, nudge exposure, warmth or highlights, step through the photos picturesq flagged for review (`f`), compare photos against every look in a grid (`g`), then **Export**. Every change is saved to `./lisbon/picturesq.yaml` as you make it.

From the command line instead:

```bash
picturesq looks                                  # the look library and each look's parameters
picturesq preview ./lisbon --category cinematic  # a contact sheet: your photos × the cinematic looks
picturesq export ./lisbon                        # web (2048 px) and archive (full size) JPEGs
```

### Wrong dates on the camera?

If the camera's clock was never set (photos dated 2000, say), tell picturesq the real time of one photo and every export is corrected by the same amount:

```bash
picturesq metadata shift ./lisbon --photo DJI_0042.DNG --actual "2026-10-17 20:05"
picturesq metadata show ./lisbon     # camera time vs corrected time, per photo
picturesq metadata apply ./lisbon    # fix the dates in exports already written
```

The UI's **Date and time** panel does the same.

## Using it with a coding agent

picturesq ships a **skill**: instructions that teach a coding agent its workflow (edit `picturesq.yaml`, render a preview, look at it) and how words map to edits ("warmer", "softer highlights", "less of the look").

```bash
picturesq skill install                     # Claude Code, every project (~/.claude/skills)
picturesq skill install --project ./lisbon  # Claude Code, this project only
picturesq skill install --dir PATH          # another agent's skills folder
picturesq skill show                        # print it, e.g. to paste into AGENTS.md
```

Then ask your agent things like *"make the sunset photos warmer and the rest nordic at 80 %"*. Keep the UI open while it works: its edits appear in the browser within a second. Rerun `picturesq skill install --force` after upgrading picturesq to get the matching skill.

Agents (and scripts) can also discover everything from the CLI itself: `picturesq looks --json`, `picturesq schema project`, `picturesq normalise PROJECT --json`. An invalid edit makes any command exit with code 2 and name the key.

## Documentation

- [Configuration reference](https://github.com/eddiemg10/picturesq/blob/main/docs/configuration.md): every key in `picturesq.yaml`, look files, and worked examples
- [Project plan](https://github.com/eddiemg10/picturesq/blob/main/docs/project-plan.md): what picturesq does and how, and the full CLI
- [Glossary](https://github.com/eddiemg10/picturesq/blob/main/docs/glossary.md): the words picturesq uses
- [Contributing](https://github.com/eddiemg10/picturesq/blob/main/CONTRIBUTING.md): development setup and releases

## Licence

MIT, except the third-party LUT files bundled with the looks, which are CC BY 4.0: see [NOTICE](https://github.com/eddiemg10/picturesq/blob/main/NOTICE).
