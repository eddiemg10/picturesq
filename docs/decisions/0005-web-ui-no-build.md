# ADR-0005: No-build web UI with Python-rendered proxies

**Status:** Accepted · 2026-10-11

## Context
We need a colour-accurate visual loop: photo × look grid and live controls, on an 8 GB CPU-only laptop, shipped via pip.

## Decision
- Starlette + uvicorn server, htmx + small vanilla JS, no Node build. Assets ship in the wheel.
- On each control change, Python renders an ~800–1200 px proxy (target < 150 ms). There is one implementation of the image maths.
- Terminal previews (sixel/kitty) are view-only and point to the UI.

## Consequences
- + Trivial install; previews are guaranteed to match exports (same code).
- − Not "buttery" like GPU editors. A WebGL path (with parity tests) is the documented upgrade if latency disappoints.
