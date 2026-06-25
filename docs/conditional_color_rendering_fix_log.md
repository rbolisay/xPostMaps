# Conditional Color Rendering Fix Log

## Regression Summary

Conditional colors must recolor the existing postplot geometry only. They must not create a dotted marker overlay for solid or dash lines, and they must not fragment dense acquisition lines into thousands of separate draw items.

## Root Causes Found

- Marker-overlay regression: affected solid/dash shotpoints were rendered as a separate dotted scatter layer. This violated the requirement and disappeared/changed behavior at different zoom levels.
- Sticky map regression: splitting polylines at each conditional color transition exploded resident GL line strips on `4030_4D` from 71 to 1858. That increased draw calls and viewport visibility checks.
- Legend apply freeze risk: conditional diff rows were refreshed on legend applies even when only symbology changed.
- Dash solid regression: GL lines cannot draw stippled/dashed strokes. The fast path must remain GL during motion, then settled zoomed-in dash detail must use CPU `PlotCurveItem` dash pens.

## Current Guardrails

- Conditional colors are stored as per-vertex/per-shotpoint RGBA arrays on the original resident geometry.
- Solid and dash conditional colors use `GLLinePlotItem` color arrays with one resident line item per original run; no conditional dotted overlay is created.
- Dotted conditional colors use `GLScatterPlotItem` color arrays inside the original scatter layer.
- Dash settled detail groups colored line runs and draws real dashed CPU curves only after pan/zoom settles and only when zoomed in.
- Conditional point calculation is skipped when the conditional-rule signature has not changed; legend color/width/style changes do not recompute Postplot 4D diffs.
- Conditional point calculation reads saved `postplot_4d_diffs` rows before calculating. If no saved rows exist for a match, it calculates once, saves the rows, then reuses them.
- Saved Postplot 4D diffs are invalidated only for changed acquisition files or the affected baseline kind when navplan/preplot file path, mtime, or size changes. Do not delete all saved diff rows on unchanged parses.

## 4030_4D Performance Check

Expected after this fix with a real conditional rule on the first postplot row:

- `gl_motion=True`
- `clip_items=0`
- `cpu_line_items=0`
- `gl_scatter_layers=0` for solid/dash conditional colors
- resident line parts stay near the baseline (`71` on the checked `4030_4D` project)

Measured during fix:

- Baseline: `gl_line_layers=2`, `parts=71`, `cpu_line_items=0`, `clip=0`, `gl_motion=True`, render about `22 ms`
- Conditional: `gl_line_layers=2`, `colored_line_layers=1`, `parts=71`, `cpu_line_items=0`, `clip=0`, `gl_motion=True`, render about `36 ms`

## Regression Tests

`tests/test_map_conditional_render.py` includes guardrails for:

- conditional colors becoming vertex colors, not marker overlays
- colored GL line geometry recoloring existing segments
- colored dash settled runs grouping into real dashed line runs
- dash pen length tracking configured millimeters
