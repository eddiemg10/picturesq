# Contributing to picturesq

## Development

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run pyright
```

See [`AGENTS.md`](AGENTS.md) for conventions and [`docs/glossary.md`](docs/glossary.md) for vocabulary.

## Releasing

Releases are manual and triggered by a `v*` tag. Pushing the tag runs the [`Release`](.github/workflows/release.yml) workflow, which builds with `uv build` and publishes to PyPI via trusted publishing (no API token).

1. Set `version` in `pyproject.toml` and `__version__` in `src/picturesq/__init__.py` (e.g. `0.1.0`) and merge it to `main` via PR. CI's `wheel` job installs the built wheel into a clean environment on Linux and Windows.
2. Tag the merge commit and push the tag:
   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```
3. Check the workflow run succeeded and the new version appears on PyPI.

The tag must match `version` in `pyproject.toml`. The `pypi` environment only accepts `v*` tags.

What the package contains: the code, the built-in looks, the web UI and the agent skill (`src/picturesq/skill/SKILL.md`). The docs are not installed; the README (the PyPI page) and the skill link to them on GitHub.
