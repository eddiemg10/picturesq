---
name: picturesq
description: Grade RAW photos with the picturesq CLI. Use when the user wants to decode, normalise, grade or export a project folder of RAW photos, or describes a look change in words ("warmer shadows", "softer highlights").
---

# picturesq (draft; completed in M5)

1. Inspect state: `picturesq normalise PROJECT --json` (stats, flags) and read `PROJECT/picturesq.yaml`.
2. Get the schema: `picturesq schema project`.
3. Render a contact sheet you can view: `picturesq preview PROJECT --png sheet.png`.
4. Translate words into config edits (mapping table to be written in M3).
5. Re-render, compare, iterate; the user makes the final taste call.
