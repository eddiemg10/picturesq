# picturesq

Turn a folder of RAW photos into consistently edited exports. No photo editor needed.

```bash
picturesq run ./trip      # develop → normalise → look → export
picturesq ui ./trip       # pick and tune looks in a tiny local web page
```

**Status:** pre-alpha (M0, setup). See [`docs/project-plan.md`](docs/project-plan.md).

- Any camera LibRaw supports; built and tested on DJI Osmo Pocket 4 DNGs
- Runs on an 8 GB, CPU-only laptop (Linux/WSL2, Windows)
- Looks grouped as B/W · Cold · Warm · Cinematic, with adjustable intensity
- Config is YAML, written by the web UI and editable by coding agents

## Development
```bash
uv sync
uv run pytest
```
See [`AGENTS.md`](AGENTS.md) for conventions.
