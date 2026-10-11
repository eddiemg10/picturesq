# picturesq

Turn a folder of RAW photos into consistently graded exports. No photo editor needed.

```bash
picturesq run ./lisbon    # decode → normalise → grade → export
picturesq ui ./lisbon     # choose looks and set their intensity in a tiny local web UI
```

**Status:** pre-alpha (M0, setup). Plan: [`docs/project-plan.md`](https://github.com/eddiemg10/picturesq/blob/main/docs/project-plan.md) · Roadmap: [project board](https://github.com/users/eddiemg10/projects/1).

- Any camera LibRaw supports; built and tested on DJI Osmo Pocket 4 DNGs
- Runs on an 8 GB, CPU-only laptop (Linux/WSL2, Windows)
- Looks in four categories (B/W · Cold · Warm · Cinematic), each with adjustable intensity
- Config is YAML, written by the web UI and editable by coding agents

## Development
```bash
uv sync
uv run pytest
```
See [`AGENTS.md`](https://github.com/eddiemg10/picturesq/blob/main/AGENTS.md) for conventions and [`docs/glossary.md`](https://github.com/eddiemg10/picturesq/blob/main/docs/glossary.md) for vocabulary.
