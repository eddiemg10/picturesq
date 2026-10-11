# ADR-0006: Binding glossary, British spelling, public repo

**Status:** Accepted · 2026-10-11

## Context
Early docs mixed vocabulary (develop/decode, strength/intensity/amount, recipe/look, profile for three different things) and spelling (colour vs `color`). The repo was planned to stay private until v0.1.

## Decision
- `docs/glossary.md` is binding for code, CLI, config, docs, issues and UI text.
- British spelling everywhere, identifiers included (`colour`, `normalise`, `grey`).
- Pipeline stages: **decode → normalise → grade → export**. A **look** is the thing applied in the grade stage; **intensity** is its strength; **adjustments** are the universal controls; **outputs** are export targets; "profile" means only ICC profile.
- Packages mirror the stages (`decode/`, `normalise/`, `grade/`, `export/`) around a shared `colour/` core. This also removes `picturesq.io`, which shadowed the stdlib name.
- The repo is public from day one (MIT), with `main` protected.

## Consequences
- + One word per concept; agents and contributors can't drift.
- + Free branch protection and required checks on a public repo.
- − British spelling is unusual for a Python CLI, and contributors need the glossary rule spelled out (AGENTS.md does this).
- − Public repo: personal RAWs must never be committed (git-ignored; goldens from CC0 samples only).
