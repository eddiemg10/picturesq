# ADR-0003: AgX-style display transform as the neutral base

**Status:** Accepted · 2026-10-11

## Context
Scene-linear data has a far larger range than a display. A display transform (tone mapping) compresses it, and its quality defines how highlights, skies and saturated colours look. Naive per-channel curves cause hue skews (blue skies to cyan, orange to yellow).

## Decision
Implement an AgX-style transform (inset primaries → log encode → sigmoid → outset), from the published maths, as the default neutral rendering. Parameters live in config.

## Consequences
- + Film-like highlight roll-off, natural path to white, good base for every look.
- − We must implement and test it ourselves. Reference implementations (Blender, darktable, AgXc) go through a licence check before any code is ported. Default: implement from the maths.
- Alternative kept in reserve: OpenDRT.
