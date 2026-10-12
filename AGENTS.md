# AGENTS.md — picturesq

Instructions for coding agents (Claude Code, Codex, …) working on this repo.
**Read this first, then `docs/project-plan.md` and `docs/glossary.md`. Don't re-explore the whole repo each session.**

## What we're building
`picturesq`: a CLI that turns a folder of RAW photos into consistently graded exports.
Pipeline stages: **decode** (rawpy → scene-linear) → **normalise** (adaptive, per photo) → **grade** (look + adjustments + AgX display transform) → **export** (outputs, sRGB JPEG).
The local web UI (`picturesq ui`) is the only way humans edit config. Agents edit the YAML or use the CLI.

- Scope, decisions, milestones: `docs/project-plan.md`
- Decision rationale: `docs/decisions/` (ADRs; add one when you make a significant decision)
- Vocabulary (binding): `docs/glossary.md`
- Concepts: `docs/learning-log.md`
- Dependencies, what each is for: `docs/dependencies.md`
- Current milestone and tasks: [project board](https://github.com/users/eddiemg10/projects/1) / GitHub issues (the only tracker)

## Hard rules
- **Vocabulary:** use only glossary terms in code, CLI, config, docs, issues and UI text. British spelling everywhere (`colour`, `normalise`, `grey`), identifiers included. New term? Add it to the glossary in the same PR.
- **Never modify originals.** Outputs go to `<dir>/.picturesq/`, `<dir>/exports/`, or `--out`.
- **Precision:** float32 scene-linear internally (linear Rec.2020 primaries); 16-bit for intermediates on disk; 8-bit only at final export. Exposure/WB maths in linear only.
- **Config over constants:** tunable values live in config models (`picturesq.config`), not inline in code.
- **Pure image operations:** `f(image: float32 HxWx3, params) -> image`, with no IO inside `colour/`, `normalise/`, `grade/`.
- **Memory:** never hold more than the needed full-res arrays; prefer in-place numpy (`out=`); interactive paths use proxies only.
- **Reproducible:** same originals + config + version = same output. Seed anything random (grain).
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
  cli/ config/ colour/ decode/ normalise/ grade/ export/ pipeline/ preview/ ui/
tests/unit  tests/integration  tests/golden
reference/   # reference set shot list + CC0 samples manifest (RAWs are git-ignored)
scripts/     # dev utilities (fetch samples, compare, update goldens)
skills/      # Claude skill shipped for end users' agents
```

## Git / PR conventions
- Branch from `main`: `feat/…`, `fix/…`, `docs/…`, `chore/…`. Squash-merge via PR; `main` is protected and CI must be green.
- PR title in conventional-commit style; body: summary, linked issue, test plan, learning note (if any).
- Update `AGENTS.md` / the project plan / glossary / ADRs when decisions change.
- The repo is **public**: never commit personal photos, absolute home paths or secrets.
