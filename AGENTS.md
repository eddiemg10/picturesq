# AGENTS.md — picturesq

Instructions for coding agents (Claude Code, Codex, …) working on this repo.
**Read this first, then `docs/project-plan.md`. Don't re-explore the whole repo each session.**

## What we're building
`picturesq`: a CLI that turns a folder of RAW photos into consistently edited exports.
Pipeline: **develop** (rawpy → scene-linear) → **normalise** (adaptive, per image) → **look** (recipe/LUT + AgX display transform) → **export** (sRGB JPEG).
A local web UI (`picturesq ui`) is the only way humans edit config. Agents edit the YAML or use the CLI.

- Scope, decisions, milestones: `docs/project-plan.md`
- Decision rationale: `docs/decisions/` (ADRs; add one when you make a significant decision)
- Concepts: `docs/learning-log.md`
- Current milestone and tasks: GitHub Project board / issues

## Hard rules
- **Never modify input files.** Outputs go to `<dir>/.picturesq/`, `<dir>/exports/`, or `--out`.
- **Precision:** float32 scene-linear internally (linear Rec.2020 primaries); 16-bit for intermediates on disk; 8-bit only at final export. Exposure/WB maths in linear only.
- **Config over constants:** tunable values live in config models (`picturesq.config`), not inline in code.
- **Pure image ops:** `f(img: float32 HxWx3, params) -> img`, with no IO inside `color/`, `normalise/`, `looks/`.
- **Memory:** never hold more than the needed full-res arrays; prefer in-place numpy (`out=`); interactive paths use proxies only.
- **Reproducible:** same input + config + version = same output. Seed anything random (grain).
- **Dependencies:** ask before adding a runtime dependency (the list is in project plan §12).
- **Tests:** maths is not merged without tests. Every PR states how it was tested.
- **Small steps:** one issue per PR; propose a plan before large changes.
- **Be honest about limits:** if something is a guess about the camera, a colour space or a LUT, say so and ask.

## Working with the user (teaching protocol)
The user is an experienced engineer but **new to image science**. Don't explain general programming. For each milestone:
1. A short concept primer (2–4 concepts, plain language, one concrete example each).
2. State trade-offs when choosing a library, colour space or algorithm.
3. Show, don't just tell: small visual/numeric demos (before/after, histograms).
4. Flag classic gotchas (wrong input space, 8-bit clipping, exposure in gamma space, …).
5. Append to `docs/learning-log.md` (concept, one paragraph, why it mattered in code).
6. Occasionally one quick understanding check at the end of a milestone; don't quiz constantly.

## Commands
```bash
uv sync                      # install env
uv run pytest                # tests
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run picturesq --help
```

## Repo map
```
src/picturesq/
  cli/ config/ io/ color/ normalise/ looks/ pipeline/ preview/ web/
tests/unit  tests/integration  tests/golden
reference/   # shot list + local RAWs (RAWs are git-ignored)
scripts/     # dev utilities (fetch samples, compare, update goldens)
skills/      # Claude skill shipped for end users' agents
```

## Git / PR conventions
- Branch from `main`: `feat/…`, `fix/…`, `docs/…`, `chore/…`. Squash-merge via PR; CI must be green.
- PR title in conventional-commit style; body: summary, linked issue, test plan, learning note (if any).
- Update `AGENTS.md` / the project plan / ADRs when decisions change.
