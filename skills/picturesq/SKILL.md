---
name: picturesq
description: Edit RAW photo looks with the picturesq CLI. Use when the user wants to develop, normalise, grade or export a folder of RAW photos, or describes a look change in words ("warmer shadows", "softer highlights").
---

# picturesq (draft; completed in M5)

1. Inspect state: `picturesq normalise DIR --json` (stats, flags) and read `DIR/picturesq.yaml`.
2. Get the schema: `picturesq schema project`.
3. Render a contact sheet you can view: `picturesq looks DIR --png /tmp/sheet.png`.
4. Translate words into config edits (mapping table to be written in M3).
5. Re-render, compare, iterate; the user makes the final taste call.
