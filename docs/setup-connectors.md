# Setting up tools and connectors

One-time setup for working on picturesq with agents.

## 1. Local tooling
- **uv** (Python env/package manager): `curl -LsSf https://astral.sh/uv/install.sh | sh`, then `uv sync` in the repo.
- **pre-commit**: `uv run pre-commit install`.
- **gh** CLI: already authenticated as `eddiemg10`.

## 2. GitHub
- Repo: `eddiemg10/picturesq` (public, MIT).
- Project board ["picturesq roadmap"](https://github.com/users/eddiemg10/projects/1) (public): Backlog → Ready → In progress → Review → Done.
- `main` is protected: PRs only, CI must pass, linear history.
- `gh` needs the `project` scope for the board: `gh auth refresh -s project`.

## 3. Claude Code on GitHub
In Claude Code, inside the repo: run `/install-github-app` and follow the prompts. This installs the Claude GitHub app and adds the workflow plus the `ANTHROPIC_API_KEY` (or OAuth) secret. You can then mention `@claude` in issues/PRs to get implementations or reviews.

## 4. Codex cloud
At chatgpt.com/codex: connect GitHub → grant access to `eddiemg10/picturesq` → create an environment for the repo (setup script: `pip install uv && uv sync`). Codex reads `AGENTS.md` automatically.

## 5. MCP servers (for Claude Code)
| Server | Status | Used for |
|---|---|---|
| Playwright | already installed | Screenshot and test the web UI (M4) |
| Figma | to add | Web UI wireframes (M4). Use Figma's official Dev Mode MCP server: enable it in the Figma desktop app (Preferences → Dev Mode MCP), then `claude mcp add --transport http figma <url shown by Figma>`. |
| GitHub | optional | `gh` CLI already covers issues/PRs; skip unless needed |

## 6. PyPI (at M5)
Create a PyPI account, then add a *pending trusted publisher* for project `picturesq` (owner `eddiemg10`, repo `picturesq`, workflow `release.yml`, environment `pypi`). This reserves the name. Consider doing it early in M0 so nobody takes the name.
