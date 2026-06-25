"""Brutal CRS + FSP/LSP audit across navplan, P111, P190 and preplot baselines.

Runs under the project venv (pyproj available). Confirms:
  * Each baseline/source file resolves to the correct EPSG (datum + projection).
  * navplan vs preplot FSP/LSP baseline positions are read/derived correctly.
  * The diff stat is small vs the navplan (steered line) and large vs the
    straight preplot (genuine feathering) - both mathematically correct.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xpostmaps.core.crs_utils import normalize_epsg
from xpostmaps.core.models import RecordType
from xpostmaps.core.postplot_4d_diff import (
    compute_postplot_4d_diff_rows,
    _generate_preplot_shotpoints,
)
from xpostmaps.parsers.metadata_parser import parse_file_metadata
from xpostmaps.parsers.p111_parser import parse_p111_file
from xpostmaps.parsers.preplot_parser import (
    parse_navplan_source_file,
    parse_preplot_file,
)

PASS = 0
FAIL = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f"  ::  {detail}" if detail else ""))
    if cond:
        PASS += 1
    else:
        FAIL += 1


def approx(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


print("=" * 78)
print("CRS + FSP/LSP BASELINE AUDIT (real data, project venv)")
print("=" * 78)

# ---- 1. CRS resolution per file type --------------------------------------
print("\n--- 1. CRS RESOLUTION PER FILE TYPE (datum + projection -> EPSG) ----")
crs_cases = [
    ("preplot p190 (4030)", "4D/4030/Preplot/4030_Mariner4D_Preplots_v2.190", "23031"),
    ("navplan p190 (4030)", "4D/4030/Navplans/Priority1/0103643A.navplan", "23031"),
    ("postplot p111 (4030)", "4D/4030/P111V/069.0103643A-069.nrt.GFUNREG.p111", "23031"),
    ("preplot p190 TRINAV", "Sample Preplots/7027_S_TRINAV_v2.p190", None),
    ("preplot p190 WGS84", "Sample Preplots/3190_TTUD1_Main_v2.WGS84.p190", None),
    ("preplot p111 WGS84", "Sample Preplots/TTUD-13D.DL2_3.WGS84.p111", None),
]
resolved: dict[str, str] = {}
for label, rel, expected in crs_cases:
    path = ROOT / rel
    if not path.is_file():
        check(f"{label}: file exists", False, rel)
        continue
    md = parse_file_metadata(path)
    epsg = normalize_epsg(md.get("epsg code", ""))
    resolved[label] = epsg
    print(f"  {label:24s} -> EPSG {epsg or '(none)':6s} "
          f"datum={md.get('geographic datum','')[:20]!r} proj={md.get('projection','')[:24]!r}")
    if expected is not None:
        check(f"{label}: EPSG == {expected}", epsg == expected, epsg or "(none)")
    else:
        check(f"{label}: a CRS was resolved", bool(epsg), epsg or "(none)")

# ---- 2. navplan vs preplot FSP/LSP positions ------------------------------
print("\n--- 2. navplan / preplot FSP & LSP BASELINE POSITIONS ---------------")
LINE = "0103643A"
preplot = parse_preplot_file(ROOT / "4D/4030/Preplot/4030_Mariner4D_Preplots_v2.190")
ctrl = sorted([r for r in preplot.records if r.line_name == LINE and r.point_num > 0],
              key=lambda r: r.point_num)
pp_gen = _generate_preplot_shotpoints(ctrl, "23031")

navplan = parse_navplan_source_file(ROOT / "4D/4030/Navplans/Priority1/0103643A.navplan")
nav = {r.point_num: r for r in navplan.records if r.point_num > 0}

src = {r.point_num: r for r in parse_p111_file(
    ROOT / "4D/4030/P111V/069.0103643A-069.nrt.GFUNREG.p111")
    if r.record_type == RecordType.SOURCE and r.point_num > 0}

fsp, lsp = min(src), max(src)
print(f"  shotpoint range: FSP={fsp} LSP={lsp}")
for tag, sp in (("FSP", fsp), ("LSP", lsp)):
    pp = pp_gen.get(sp)
    nv = nav.get(sp)
    sc = src.get(sp)
    print(f"  {tag} {sp}: preplot=({pp.x:.2f},{pp.y:.2f})  "
          f"navplan=({nv.x:.2f},{nv.y:.2f})  source=({sc.x:.2f},{sc.y:.2f})")

# navplan FSP/LSP should be the raw S-record control coords (not interpolated).
check("navplan FSP read directly from file", fsp in nav and nav[fsp].x > 0)
check("navplan LSP read directly from file", lsp in nav and nav[lsp].x > 0)
# source endpoints must track the navplan endpoints (steered line) closely...
d_fsp_nav = math.hypot(src[fsp].x - nav[fsp].x, src[fsp].y - nav[fsp].y)
d_lsp_nav = math.hypot(src[lsp].x - nav[lsp].x, src[lsp].y - nav[lsp].y)
print(f"  source-vs-navplan: FSP {d_fsp_nav:.2f} m   LSP {d_lsp_nav:.2f} m")
check("source FSP within 5 m of navplan FSP", d_fsp_nav < 5.0, f"{d_fsp_nav:.2f}")
check("source LSP within 5 m of navplan LSP (steered line)", d_lsp_nav < 5.0, f"{d_lsp_nav:.2f}")
# ...and diverge from the STRAIGHT preplot toward the line end (feathering).
d_lsp_pp = math.hypot(src[lsp].x - pp_gen[lsp].x, src[lsp].y - pp_gen[lsp].y)
print(f"  source-vs-preplot: LSP {d_lsp_pp:.2f} m (straight preplot, expect feathering)")
check("source LSP is far from straight preplot LSP (feathering real)",
      d_lsp_pp > 20.0, f"{d_lsp_pp:.2f}")

# ---- 3. diff stat vs each baseline ----------------------------------------
print("\n--- 3. DIFF STAT MAGNITUDE BY BASELINE ------------------------------")
nav_baseline = {sp: __import__("xpostmaps.core.postplot_4d_diff", fromlist=["BaselineShotpoint"]).BaselineShotpoint(
    shotpoint=sp, x=r.x, y=r.y) for sp, r in nav.items()}
rows_nav = compute_postplot_4d_diff_rows(nav_baseline, src, "123.1")
rows_pp = compute_postplot_4d_diff_rows(pp_gen, src, "123.1")
max_rad_nav = max(r.radial_m for r in rows_nav)
max_rad_pp = max(r.radial_m for r in rows_pp)
mean_rad_nav = sum(r.radial_m for r in rows_nav) / len(rows_nav)
print(f"  vs navplan: rows={len(rows_nav)} mean radial={mean_rad_nav:.2f} m max={max_rad_nav:.2f} m")
print(f"  vs preplot: rows={len(rows_pp)} max radial={max_rad_pp:.2f} m")
check("diff vs navplan is small (steered line acceptance)", max_rad_nav < 5.0, f"{max_rad_nav:.2f}")
check("diff vs preplot is large (straight line, feathering)", max_rad_pp > 20.0, f"{max_rad_pp:.2f}")

print("\n" + "=" * 78)
print(f"RESULT: {PASS} passed, {FAIL} failed")
print("=" * 78)
sys.exit(1 if FAIL else 0)
