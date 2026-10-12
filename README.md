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
- Config is YAML, written by the web UI and editable by coding agents: see [`docs/configuration.md`](https://github.com/eddiemg10/picturesq/blob/main/docs/configuration.md)

## Development
```bash
uv sync
uv run pytest
```
See [`AGENTS.md`](https://github.com/eddiemg10/picturesq/blob/main/AGENTS.md) for conventions and [`docs/glossary.md`](https://github.com/eddiemg10/picturesq/blob/main/docs/glossary.md) for vocabulary.

## Releasing
Releases are manual for now and triggered by a `v*` tag. Pushing the tag runs the [`Release`](https://github.com/eddiemg10/picturesq/blob/main/.github/workflows/release.yml) workflow, which builds with `uv build` and publishes to PyPI via trusted publishing (no API token).

1. Set `version` in `pyproject.toml` (e.g. `0.0.1`) and merge it to `main` via PR.
2. Tag the merge commit and push the tag:
   ```bash
   git tag v0.0.1
   git push origin v0.0.1
   ```
3. Check the workflow run succeeded and the new version appears on PyPI.

The tag must match `version` in `pyproject.toml`. The `pypi` environment only accepts `v*` tags.
