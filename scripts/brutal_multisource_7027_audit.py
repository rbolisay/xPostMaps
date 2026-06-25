"""Brutal multi-source (flip-flop) validation on the real 7027 TRINAV survey.

Verifies the preplot source-separation handling end-to-end:
  * Header: NUMBER OF SOURCES=2, SOURCE SEPARATION=50 m, HEADING=125, EPSG 32621.
  * Generated baseline places the two sources +/-25 m crossline, 50 m apart,
    perpendicular to the line, centred on the interpolated preplot centre line.
  * The diff pipeline compares firing G01 to baseline source-1 and G02 to
    baseline source-2 (NOT the line centre) -> small crossline residuals.
  * Proves separation is accounted for: a naive centre-line diff would leave a
    ~25 m crossline bias that the real pipeline removes.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xpostmaps.core.models import MapData, ProjectSettings, RecordType
from xpostmaps.core.postplot_4d_diff import (
    _generate_preplot_shotpoints,
    _read_preplot_generation_info,
    calculate_match_diff_rows,
    compute_postplot_4d_diff_rows,
    load_baseline_shotpoints,
)
from xpostmaps.core.postplot_4d_matching import build_postplot_4d_rows
from xpostmaps.parsers.p111_parser import parse_p111_file
from xpostmaps.parsers.preplot_parser import parse_preplot_files
from xpostmaps.parsers.sequence_builder import build_display_sequences

PREPLOT = ROOT / "4D/7027/Preplot/7027_S_TRINAV_v2.p190"
P111_DIR = ROOT / "4D/7027/P111V_S"
P111 = P111_DIR / "3237.53196213237.a3237.GFUNREG.p111"

PASS = 0
FAIL = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f"  ::  {detail}" if detail else ""))
    if cond:
        PASS += 1
    else:
        FAIL += 1


print("=" * 78)
print("BRUTAL MULTI-SOURCE 7027 (flip-flop) PREPLOT DIFF AUDIT")
print("=" * 78)

# ---- 1. header ------------------------------------------------------------
info = _read_preplot_generation_info(PREPLOT)
print(f"header: sources={info.number_of_sources} sep={info.source_separation_m} "
      f"dir={info.line_direction!r} interval={info.shotpoint_interval_m}")
check("NUMBER OF SOURCES == 2", info.number_of_sources == 2, str(info.number_of_sources))
check("SOURCE SEPARATION == 50.0 m", info.source_separation_m == 50.0, str(info.source_separation_m))
check("HEADING == 125.00 deg", info.line_direction == "125.00°", info.line_direction)
check("SHOT POINT INTERVAL == 25.0 m", info.shotpoint_interval_m == 25.0, str(info.shotpoint_interval_m))

# ---- 2. parse preplot + find the line matching the P111 acquisition -------
segments, _meta, _stats = parse_preplot_files([PREPLOT])
map_data = MapData()
map_data.preplot_segments = segments

src_records = [r for r in parse_p111_file(P111) if r.record_type == RecordType.SOURCE]
map_data.positions = src_records
map_data.sequences = build_display_sequences(src_records)
acq_line = src_records[0].line_name
print(f"\nacquired P111 line = {acq_line!r}, {len(src_records)} firing sources "
      f"(G01 + G02 flip-flop)")

settings = ProjectSettings(
    preplot_files=[str(PREPLOT.resolve())],
    nav_files=[str(P111.resolve())],
    postplot_4d_baseline="preplot",
)

rows = build_postplot_4d_rows(map_data, settings, "preplot")
matched = [r for r in rows if r.has_match]
print(f"preplot match rows: {len(rows)} total, {len(matched)} matched")
check("acquired line matched to a preplot baseline", len(matched) >= 1,
      f"{[ (m.baseline_name, m.line_name) for m in matched[:3] ]}")
if not matched:
    print("\nRESULT:", PASS, "passed", FAIL, "failed (cannot continue without a match)")
    sys.exit(1)

match_row = matched[0]
baseline_name = match_row.baseline_name
print(f"matched baseline={baseline_name!r} <- acquired line={match_row.line_name!r}")

# ---- 3. generated baseline geometry: two sources, 50 m apart, +/-25 -------
baseline = load_baseline_shotpoints(
    map_data, settings, "preplot", baseline_name, match_row.baseline_file_name,
    map_epsg="32621",
)
# keys are (sp, '1') / (sp, '2'); pick a shotpoint present for both sources
sps_with_both = sorted({
    k[0] for k in baseline if isinstance(k, tuple) and (k[0], "2") in baseline and (k[0], "1") in baseline
})
print(f"baseline keys multi-source: {sum(isinstance(k, tuple) for k in baseline)} "
      f"shotpoints-with-both={len(sps_with_both)}")
check("baseline keyed per (shotpoint, source)", len(sps_with_both) > 50, str(len(sps_with_both)))

theta = math.radians(125.0)
sep_err = 0.0
perp_err = 0.0
center_err = 0.0
for sp in sps_with_both:
    s1 = baseline[(sp, "1")]
    s2 = baseline[(sp, "2")]
    d = math.hypot(s1.x - s2.x, s1.y - s2.y)
    sep_err = max(sep_err, abs(d - 50.0))
    # vector s1->s2 should be along crossline (perpendicular to heading)
    vx, vy = s2.x - s1.x, s2.y - s1.y
    inline_comp = vx * math.sin(theta) + vy * math.cos(theta)  # along-line component
    perp_err = max(perp_err, abs(inline_comp))
print(f"max |source1-source2 distance - 50 m| = {sep_err:.6f} m")
print(f"max along-line component of source1->source2 = {perp_err:.6f} m (should be ~0)")
check("two baseline sources are exactly 50 m apart", sep_err < 1e-3, f"{sep_err:.2e}")
check("source1->source2 is purely crossline (perp. to heading)", perp_err < 1e-3, f"{perp_err:.2e}")

# centre of the two baseline sources must equal the single-source centre line
from xpostmaps.parsers.preplot_parser import parse_preplot_file

preplot_controls = sorted(
    [rec for rec in parse_preplot_file(PREPLOT).records
     if rec.line_name == baseline_name and rec.point_num > 0],
    key=lambda r: r.point_num,
)
center_only = _generate_preplot_shotpoints(preplot_controls, "32621")
for sp in sps_with_both[:200]:
    s1 = baseline[(sp, "1")]
    s2 = baseline[(sp, "2")]
    cx, cy = (s1.x + s2.x) / 2.0, (s1.y + s2.y) / 2.0
    c = center_only.get(sp)
    if c is not None:
        center_err = max(center_err, math.hypot(cx - c.x, cy - c.y))
print(f"max |midpoint(src1,src2) - single-source centre| = {center_err:.6f} m")
check("two sources are centred on the preplot centre line", center_err < 1e-6, f"{center_err:.2e}")

# ---- 4. the diff compares each firing gun to ITS OWN baseline source ------
diff_rows = calculate_match_diff_rows(map_data, settings, src_records, match_row)
print(f"\ncomputed {len(diff_rows)} diff rows")
check("diff rows produced for multi-source line", len(diff_rows) > 50, str(len(diff_rows)))

# Separate residuals by firing gun.
src_by_sp = {r.point_num: r for r in src_records}
g01_cross = []
g02_cross = []
naive_g01_cross = []  # crossline if compared against the CENTRE line instead
for row in diff_rows:
    rec = src_by_sp.get(row.shotpoint)
    if rec is None:
        continue
    if rec.source_id == "G01":
        g01_cross.append(row.crossline_m)
    elif rec.source_id == "G02":
        g02_cross.append(row.crossline_m)
    # naive centre comparison
    c = center_only.get(row.shotpoint)
    if c is not None and rec.source_id == "G01":
        de, dn = rec.x - c.x, rec.y - c.y
        naive_g01_cross.append(de * math.cos(theta) - dn * math.sin(theta))


def stats(name, vals):
    if not vals:
        print(f"  {name}: (none)")
        return 0.0
    mean = sum(vals) / len(vals)
    mx = max(abs(v) for v in vals)
    print(f"  {name}: n={len(vals)} mean={mean:+.2f} m  max|.|={mx:.2f} m")
    return abs(mean)


print("crossline residual by firing gun (diff vs its OWN baseline source):")
g01_bias = stats("G01 vs baseline source-1", g01_cross)
g02_bias = stats("G02 vs baseline source-2", g02_cross)
naive_bias = stats("G01 vs CENTRE line (naive, wrong)", naive_g01_cross)

check("G01 residual crossline is small (separation accounted for, correct side)",
      g01_bias < 5.0, f"mean|bias|={g01_bias:.2f} m")
check("G02 residual crossline is small (separation accounted for, correct side)",
      g02_bias < 5.0, f"mean|bias|={g02_bias:.2f} m")
check("naive centre-line diff shows ~25 m bias (proves separation matters)",
      naive_bias > 15.0, f"mean|bias|={naive_bias:.2f} m")

# ---- 5. diff math identity on multi-source rows ---------------------------
worst = 0.0
for row in diff_rows:
    worst = max(worst, abs(row.radial_m - math.hypot(row.inline_m, row.crossline_m)))
check("radial == hypot(inline, crossline) on every multi-source row",
      worst < 1e-9, f"{worst:.2e}")

print("\n" + "=" * 78)
print(f"RESULT: {PASS} passed, {FAIL} failed")
print("=" * 78)
sys.exit(1 if FAIL else 0)
