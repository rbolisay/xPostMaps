# PDF export

xPostMaps writes print-ready PDFs from the current map view and right pane. The default path is a **hybrid vector export**: postplot geometry is true PDF vector content (sharp at any zoom), while the right pane (legend, minimap, text) is re-rendered as a high-resolution bitmap beside the map.

This path is separate from the interactive map. Pan/zoom performance is unchanged by export quality settings.

---

## Export to PDF dialog

Open from the main menu: **Export to PDF**.

| Control | Default | Purpose |
|---------|---------|---------|
| **Paper size** | A3 | ISO or North American sheet size |
| **Resolution (DPI)** | 600 | Actual export resolution for both hybrid vector and raster modes |
| **Orientation** | Landscape | Portrait or landscape page layout |
| **Margins** | Default (10 mm) | Presets or custom margin in millimetres |
| **Scale** | Default | Fit content on page, actual size, or custom % |
| **High-quality PDF layout** | On | Hybrid vector map + sharp right pane (recommended) |
| **Map detail** | 100 | Geometry simplification for vector export (only when high-quality is on) |
| **Open folder after export** | On | Opens Explorer with the saved PDF selected |

Live preview on the right updates when paper, margins, scale, or export options change.

---

## Recommended settings

For best detail and zoom sharpness on postplot linework:

1. Leave **High-quality PDF layout** checked.
2. Set **Map detail** to **100** (full visible geometry).
3. Use **600 DPI** and **A3 landscape** for normal output; use **1200 DPI** for extra print-pixel detail, or **2000 DPI** only for extreme close-review exports where larger files / slower export are acceptable.
4. Pan/zoom the map to the area you want before exporting — only the **current view** is exported.

Typical results on `7027.db` (A3, 600 DPI, Map detail 100):

| Style | Zoomed view | Full extent |
|-------|-------------|-------------|
| Solid | ~4 MB, ~1.5 s | ~12 MB, ~4 s |
| Dash | ~4 MB, ~1.7 s | ~12 MB, ~4 s |
| Dotted | ~5.5 MB, ~2.4 s | ~12.5 MB, ~4.3 s |

Dotted exports are slightly larger because each shotpoint is a vector marker. A shared dot budget keeps very dense multi-colour surveys bounded (~220k round points per page across all dotted layers).

---

## Export modes

### High-quality PDF layout (recommended) — hybrid vector

When checked, export uses `compose_pdf_hybrid`:

1. Hide the OpenGL overlay (GPU layers are not written to the PDF scene directly).
2. Build full-resolution CPU geometry for the visible viewport:
   - **Solid / dash** → `PlotCurveItem` polylines with print-weight pens.
   - **Dotted** → `VectorDotsItem` round vector points (not raster scatter).
3. Render the pyqtgraph scene through `QPdfWriter` as true vector paths.
4. Render the right pane separately and draw it beside the map.

**Result:** Postplot lines and dotted markers stay sharp when zooming inside the PDF viewer. File size stays moderate because geometry is clipped to the view and dotted markers use efficient vector points instead of per-dot Bezier ellipses or bitmap symbols.

The selected **Resolution (DPI)** is used directly by `QPdfWriter`. For the same paper size, **1200 DPI gives 2× pixels per side and 4× page pixel area compared with 600 DPI**; **2000 DPI gives about 3.33× pixels per side and 11.1× page pixel area**. That gives the Map detail logic and dotted marker deduplication a finer print-pixel grid, but it can increase file size and export time.

### High-quality off — screen capture

When unchecked, export grabs the map as displayed (screen / composite bitmap) and embeds it in the PDF. The right pane is still re-rendered for crisp text.

- **Faster** for a quick WYSIWYG snapshot.
- **Pixelates** when zoomed — not suitable for print review of linework detail.
- **Map detail** is disabled and ignored.
- Raster compositing also uses the selected **Resolution (DPI)**. High DPI raster exports can create very large images, especially on A0/A1 paper.

Raster export runs compositing on a background thread after capture; hybrid vector export runs on the UI thread with a progress dialog.

---

## Map detail slider

**Only applies when High-quality PDF layout is on.**

| Value | Behaviour |
|-------|-----------|
| **100** | Full geometry for the visible view — matches the settled map detail. Default and recommended. |
| **Below 100** | Print-resolution decimation via `VectorExportContext` in `vector_export.py`. |

Decimation is applied in **device pixel space** at the PDF map rectangle size:

- **Solid / dash lines:** Douglas–Peucker simplification — drops vertices that fall within the same print pixel. Preserves shape at page scale; removes sub-pixel noise.
- **Dotted markers:** Pixel-grid deduplication and clustering — merges markers that would overlap on the page.

Lower Map detail → fewer paths/points → faster export and smaller PDF, with some loss of fine structure when zooming deep into the PDF.

At **100**, dotted layers still use an internal **dot budget** (`_GLOBAL_EXPORT_DOT_BUDGET = 220_000`, split across dotted colour layers) so saturated full-extent views do not emit millions of redundant overlapping markers.

---

## Postplot line styles in PDF

| Style | On-screen (interactive) | PDF export (hybrid) |
|-------|-------------------------|---------------------|
| **Solid** | GPU line strips when dense; full vertex detail on settle | Full-resolution polyline vectors; print-weight pen (`0.35×` legend mm width at 300 DPI reference) |
| **Dash** | GPU strips at survey scale; CPU dash curves when deeply zoomed | Polyline vectors with **explicit custom dash pattern** `[16, 8]` so dashes stay visible at hairline print weight |
| **Dotted** | GPU scatter — one marker per shotpoint | **Round vector points** via `VectorDotsItem` — cosmetic diameter, deduped and budget-capped; not raster `ScatterPlotItem` |

### Why dotted uses vector points

Earlier paths used `pg.ScatterPlotItem(pxMode=True)`, which pyqtgraph renders through a **raster symbol atlas**. In PDF that became hundreds of tiny embedded images — large files, slow export, and blurry dots when zoomed.

`VectorDotsItem` draws markers as `drawPoints` with a round-cap cosmetic pen at fixed page-pixel size. One stroke per shotpoint, scalable, and much smaller than four Bezier curves per ellipse.

### Why dash uses a custom pattern

Qt’s default dash pattern scales with pen width. Print-weight export pens are very thin (~0.25–0.6 px cosmetic), so the default pattern collapsed to a nearly solid stroke in PDF viewers. The explicit `[16, 8]` pattern keeps dashes readable without thick screen-weight lines that hide survey zig-zag detail.

---

## Architecture

```
Export to PDF dialog
        │
        ├─ High-quality ON ──► compose_pdf_hybrid()
        │                           │
        │                           ├─ build_vector_export_context()  [if Map detail < 100]
        │                           ├─ map_widget.prepare_for_export(wysiwyg=False)
        │                           │       ├─ hide GL overlay
        │                           │       ├─ ResidentGlLineLayer.prepare_export()
        │                           │       ├─ ResidentGlScatterLayer.prepare_export()
        │                           │       └─ _restore_export_detail(use_export_pens=True)
        │                           ├─ QPdfWriter + render_vector()  → vector map
        │                           └─ render_pane_for_export()      → bitmap right pane
        │
        └─ High-quality OFF ──► capture_export_images(wysiwyg=True)
                                    └─ screen grab + compose_pdf_to_path() [background worker]
```

### Key modules

| File | Role |
|------|------|
| `xpostmaps/ui/dialogs/pdf_export_dialog.py` | Dialog UI, preview, export orchestration |
| `xpostmaps/core/pdf_export.py` | Page layout, hybrid/raster composition, `PdfExportOptions` |
| `xpostmaps/core/pdf_export_worker.py` | Background PDF write for raster mode |
| `xpostmaps/ui/map_widget.py` | `prepare_for_export`, `render_vector`, export pens, dot budget |
| `xpostmaps/ui/map_gl_resident_layer.py` | GL → CPU curves for solid/dash export |
| `xpostmaps/ui/map_gl_resident_scatter_layer.py` | GL → `VectorDotsItem` for dotted export |
| `xpostmaps/ui/map_vector_dots.py` | Round vector shotpoint markers for PDF |
| `xpostmaps/utils/vector_export.py` | Print-pixel decimation (Map detail < 100) |
| `xpostmaps/ui/right_pane.py` | Sharp legend/minimap render for export |

### Constants (tuning reference)

| Constant | Location | Value | Meaning |
|----------|----------|-------|---------|
| `PDF_EXPORT_DPI` | `symbology_units.py` | 300 | Reference DPI for export pen/symbol sizing |
| `_EXPORT_LINE_WIDTH_SCALE` | `map_widget.py` | 0.35 | Print line weight vs legend mm |
| `_EXPORT_DOT_SIZE_SCALE` | `map_widget.py` | 0.5 | Dotted marker diameter scale for PDF |
| `_GLOBAL_EXPORT_DOT_BUDGET` | `map_widget.py` | 220_000 | Max dotted points per page (all layers) |

---

## Interaction vs export

The interactive map and PDF export use **different rendering paths** on purpose:

| | Interactive map | PDF export |
|--|-----------------|------------|
| Dense solid/dash | GPU line strips (transform-only pan) | CPU polylines → PDF vectors |
| Dense dotted | GPU scatter | CPU round vector points |
| Motion LOD | Coarse geometry while panning | Not used — full view geometry |
| Line weight | Screen DPI cosmetic pens | Print-weight export pens |

Export never slows pan/zoom. `prepare_for_export` / `end_export` swap geometry only during the export operation.

---

## Troubleshooting

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| PDF pixelates when zoomed | High-quality off (raster mode) | Enable **High-quality PDF layout** |
| Lines look too thick / lose zig-zag detail | Screen-weight pens or oversized markers | Use hybrid mode (current default); Map detail 100 |
| Dash looks solid | Old export without custom dash pattern | Update to current build; use hybrid mode |
| Dotted looks blobby | Old raster scatter export | Update to current build; `VectorDotsItem` path |
| Export slow / huge file on dotted full extent | Very dense shotpoints across whole survey | Zoom to area of interest, or lower **Map detail** |
| Map detail slider greyed out | High-quality off | Enable high-quality layout to use the slider |

---

## Related docs

- [Map Optimization.md](Map%20Optimization.md) — interactive God Mode path (GPU resident layers, motion LOD)
- [interactive-map-performance.md](interactive-map-performance.md) — performance notes and export checklist

---

*Last updated: 2026-06-23 — hybrid vector export with `VectorDotsItem`, custom dash pattern, and Map detail decimation.*
