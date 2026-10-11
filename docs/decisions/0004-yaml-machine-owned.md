# ADR-0004: YAML config is machine-owned; web UI is the human editor

**Status:** Accepted · 2026-10-11

## Context
Config must be portable, reproducible and editable by coding agents. The user does not want to hand-edit YAML.

## Decision
- Pydantic models are the source of truth; YAML is their serialisation; `picturesq schema` exports JSON Schema.
- Humans edit through `picturesq ui`; agents edit the file or use CLI commands.
- Writes are atomic (temp file + rename); the UI watches the file and reloads on external change.
- Comments in YAML are not preserved (nobody hand-writes them).

## Consequences
- + Simple serializer; strict validation; agents get a schema.
- − Every user-tunable setting needs a UI control before humans can change it, so the UI scope must be managed.
