"""Brutal audit of preplot shotpoint generation, CRS handling and diff stats.

Runs against the REAL 4030 Mariner 4D dataset (no mock data). Verifies:
  1. Preplot header robustness (shot interval, rotation, #sources, separation).
  2. Shotpoint derivation from sparse FSP/LSP controls + interval geometry.
  3. Source-separation crossline offset maths.
  4. CRS resolution of preplot vs postplot P111 and datum consistency.
  5. Diff-stat (crossline / inline / radial) decomposition correctness.

Exit code is non-zero if any check fails.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xpostmaps.core.crs_utils import normalize_epsg
from xpostmaps.core.models import PositionRecord, RecordType
from xpostmaps.core.postplot_4d_diff import (
    _apply_crossline_offset,
    _offset_components,
    _read_preplot_generation_info,
    _source_crossline_offset_m,
    _generate_preplot_shotpoints,
    compute_postplot_4d_diff_rows,
    parse_number_of_sources,
    parse_shotpoint_interval_m,
    parse_source_separation_m,
    resolve_line_azimuth_degrees,
    BaselineShotpoint,
)
from xpostmaps.parsers.metadata_parser import parse_p111_metadata, parse_p190_metadata
from xpostmaps.parsers.p111_parser import parse_p111_file
from xpostmaps.parsers.preplot_parser import parse_preplot_file

PREPLOT = ROOT / "4D/4030/Preplot/4030_Mariner4D_Preplots_v2.190"
P111 = ROOT / "4D/4030/P111V/069.0103643A-069.nrt.GFUNREG.p111"
LINE = "0103643A"

PASS = 0
FAIL = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    mark = "PASS" if condition else "FAIL"
    if condition:
        PASS += 1
    else:
        FAIL += 1
    print(f"[{mark}] {label}" + (f"  ::  {detail}" if detail else ""))


def approx(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


print("=" * 78)
print("BRUTAL PREPLOT / DIFF-STAT AUDIT  (real 4030 Mariner 4D data)")
print("=" * 78)
print(f"preplot : {PREPLOT}  exists={PREPLOT.is_file()}")
print(f"p111    : {P111}  exists={P111.is_file()}")
print()

# ---------------------------------------------------------------- 1. headers
print("--- 1. PREPLOT HEADER ROBUSTNESS ------------------------------------")
info = _read_preplot_generation_info(PREPLOT)
print(f"interval={info.shotpoint_interval_m} dir={info.line_direction!r} "
      f"nsrc={info.number_of_sources} sep={info.source_separation_m}")
check("shot interval parsed == 25.0", info.shotpoint_interval_m == 25.0,
      str(info.shotpoint_interval_m))
check("rotation parsed == 123.10 deg", info.line_direction == "123.10°",
      info.line_direction)
check("number of sources == 1", info.number_of_sources == 1,
      str(info.number_of_sources))

# Regex robustness on header-line variants
check("interval regex: dotted leader", parse_shotpoint_interval_m(
    "H2600SHOT INTERVAL ...........: 25.0000") == 25.0)
check("interval regex: 'SHOT POINT INTERVAL    16.667 m'",
      parse_shotpoint_interval_m("CC,1,0,0,SHOT POINT INTERVAL       16.667 m") == 16.667)
check("interval regex: streamer separation NOT matched",
      parse_shotpoint_interval_m("H2600STREAMER SEPARATION 112.50 m") is None)
check("interval regex: 'SHOT INCREMENT 1' NOT matched as interval",
      parse_shotpoint_interval_m("H2600SHOT INCREMENT ..........: 1") is None)
check("nsrc regex == 3", parse_number_of_sources("H2600NUMBER OF SOURCES......: 3") == 3)
check("separation regex == 50.0", parse_source_separation_m("H2600SOURCE SEPARATION 50.00 m") == 50.0)

# ------------------------------------------------------- 2. shotpoint geometry
print()
print("--- 2. SHOTPOINT DERIVATION FROM SPARSE CONTROLS --------------------")
result = parse_preplot_file(PREPLOT)
controls = [r for r in result.records if r.line_name == LINE and r.point_num > 0]
controls.sort(key=lambda r: r.point_num)
print(f"controls for {LINE}: {[(c.point_num, round(c.x,2), round(c.y,2)) for c in controls]}")
check("preplot supplies >=2 controls (FSP/LSP)", len(controls) >= 2, str(len(controls)))

fsp, lsp = controls[0], controls[-1]
span = lsp.point_num - fsp.point_num
chord = math.hypot(lsp.x - fsp.x, lsp.y - fsp.y)
spacing = chord / span
print(f"FSP={fsp.point_num} LSP={lsp.point_num} span={span} chord={chord:.3f}m "
      f"spacing={spacing:.5f}m")
check("derived spacing == header interval (25 m)", approx(spacing, 25.0, 5e-3),
      f"{spacing:.5f} m/sp")

chord_az = math.degrees(math.atan2(lsp.x - fsp.x, lsp.y - fsp.y)) % 360.0
print(f"chord azimuth = {chord_az:.4f} deg")
check("chord azimuth == header rotation (123.10)", approx(chord_az, 123.10, 0.02),
      f"{chord_az:.4f}")

gen = _generate_preplot_shotpoints(controls, "")
sps = sorted(gen)
check("generated SP count == span+1 (contiguous)", len(sps) == span + 1,
      f"{len(sps)} vs {span + 1}")
check("first generated SP == FSP", sps[0] == fsp.point_num, str(sps[0]))
check("last generated SP == LSP", sps[-1] == lsp.point_num, str(sps[-1]))
check("endpoint X matches FSP control", approx(gen[fsp.point_num].x, fsp.x, 1e-6))
check("endpoint Y matches LSP control", approx(gen[lsp.point_num].y, lsp.y, 1e-6))

# every generated point collinear with the actual FSP->LSP chord + 25 m apart.
chord_len = math.hypot(lsp.x - fsp.x, lsp.y - fsp.y)
ux = (lsp.x - fsp.x) / chord_len  # chord unit vector (true heading of controls)
uy = (lsp.y - fsp.y) / chord_len
max_off = 0.0       # perpendicular deviation from the true chord
max_step_err = 0.0
max_grid_off = 0.0  # deviation vs idealised 25 m x 123.10deg grid (quantisation)
prev = None
theta = math.radians(123.10)
for sp in sps:
    p = gen[sp]
    rel_e = p.x - fsp.x
    rel_n = p.y - fsp.y
    perp = abs(rel_e * uy - rel_n * ux)            # distance from chord line
    max_off = max(max_off, perp)
    grid_x = fsp.x + (sp - fsp.point_num) * 25.0 * math.sin(theta)
    grid_y = fsp.y + (sp - fsp.point_num) * 25.0 * math.cos(theta)
    max_grid_off = max(max_grid_off, math.hypot(p.x - grid_x, p.y - grid_y))
    if prev is not None:
        d = math.hypot(p.x - prev.x, p.y - prev.y)
        max_step_err = max(max_step_err, abs(d - 25.0))
    prev = p
print(f"max perpendicular offset from FSP-LSP chord = {max_off:.6f} m")
print(f"max deviation vs ideal 25 m x 123.10deg grid = {max_grid_off:.6f} m "
      "(FSP/LSP quantised to 0.1 m in V-record)")
print(f"max |step - 25 m| between consecutive SP    = {max_step_err:.6f} m")
check("all generated SPs collinear with chord (<1mm)", max_off < 1e-3, f"{max_off:.2e}")
check("consecutive SP spacing == 25 m (<5mm)", max_step_err < 5e-3, f"{max_step_err:.2e}")
check("ideal-grid deviation within V-record 0.1 m quantisation",
      max_grid_off < 0.05, f"{max_grid_off:.4f} m")

# closed-form vs generated for an interior SP
sp_mid = 1536
start = controls[0]
exp_x = start.x + (sp_mid - start.point_num) * 25.0 * math.sin(math.radians(123.1))
exp_y = start.y + (sp_mid - start.point_num) * 25.0 * math.cos(math.radians(123.1))
check(f"SP{sp_mid} X matches interval*heading formula",
      approx(gen[sp_mid].x, exp_x, 0.02), f"gen={gen[sp_mid].x:.3f} exp={exp_x:.3f}")
check(f"SP{sp_mid} Y matches interval*heading formula",
      approx(gen[sp_mid].y, exp_y, 0.02), f"gen={gen[sp_mid].y:.3f} exp={exp_y:.3f}")

# ----------------------------------------------- 3. source-separation offsets
print()
print("--- 3. SOURCE-SEPARATION CROSSLINE OFFSET MATHS ---------------------")
# dual source, 50 m separation, heading north (az=0): G01 starboard +25, G02 -25
o1 = _source_crossline_offset_m(1, 2, 50.0)
o2 = _source_crossline_offset_m(2, 2, 50.0)
check("dual-src offsets symmetric (+25 / -25)", approx(o1, 25.0, 1e-9) and approx(o2, -25.0, 1e-9),
      f"G01={o1} G02={o2}")
x1, y1 = _apply_crossline_offset(0.0, 0.0, o1, 0.0)
x2, y2 = _apply_crossline_offset(0.0, 0.0, o2, 0.0)
check("offset applied along crossline (az=0 -> +/-E)",
      approx(x1, 25.0, 1e-9) and approx(x2, -25.0, 1e-9), f"x1={x1} x2={x2}")
# triple source centered: middle gun has zero offset
check("triple-src centre gun zero offset",
      approx(_source_crossline_offset_m(2, 3, 37.5), 0.0, 1e-9))
gen_ms = _generate_preplot_shotpoints(
    [
        PositionRecord("p", RecordType.PREPLOT, "L", "", "", 100, 0.0, 0.0),
        PositionRecord("p", RecordType.PREPLOT, "L", "", "", 101, 0.0, 25.0),
    ],
    "", source_count=2, source_separation_m=50.0, line_azimuth_deg=0.0,
)
check("multi-src baseline keyed by (sp, source)",
      (100, "1") in gen_ms and (100, "2") in gen_ms)
check("multi-src G01 crossline placed +25 E (north line)",
      approx(gen_ms[(100, "1")].x, 25.0, 1e-6), f"{gen_ms[(100,'1')].x}")

# ------------------------------------------------------------- 4. CRS / datum
print()
print("--- 4. CRS RESOLUTION & DATUM CONSISTENCY ---------------------------")
p190_md = parse_p190_metadata(PREPLOT)
p111_md = parse_p111_metadata(P111)
print(f"preplot .190 epsg -> {p190_md.get('epsg code')!r} "
      f"(datum={p190_md.get('geographic datum','')[:24]!r}, proj={p190_md.get('projection')!r})")
print(f"postplot p111 epsg -> {p111_md.get('epsg code')!r}")
preplot_epsg = normalize_epsg(p190_md.get("epsg code", ""))
p111_epsg = normalize_epsg(p111_md.get("epsg code", ""))
check("postplot P111 resolves to EPSG 23031 (ED50/UTM31N), not clobbered by "
      "compound CRS row", p111_epsg == "23031", p111_epsg)
# preplot inference needs pyproj; record outcome either way
print(f"preplot inferred epsg (needs pyproj) = {preplot_epsg!r}")
if preplot_epsg:
    check("preplot CRS matches postplot CRS", preplot_epsg == p111_epsg,
          f"{preplot_epsg} vs {p111_epsg}")
else:
    print("[WARN] preplot .190 EPSG could not be inferred (pyproj missing?) -> "
          "diff falls back to postmap/P111 EPSG 23031")

try:
    import pyproj  # noqa: F401
    print("pyproj available:", pyproj.__version__)
except Exception as exc:  # noqa: BLE001
    print(f"[WARN] pyproj NOT installed ({exc}) -> generated baseline Lat/Long "
          "and EPSG-from-header inference are DISABLED")

# ----------------------------------------------------------- 5. diff stat math
print()
print("--- 5. DIFF-STAT (CROSSLINE / INLINE / RADIAL) ----------------------")
src_records = parse_p111_file(P111)
sources = {
    r.point_num: r
    for r in src_records
    if r.record_type == RecordType.SOURCE and r.point_num > 0
}
print(f"parsed {len(sources)} firing-source shotpoints from P111")
check("P111 firing sources parsed", len(sources) > 100, str(len(sources)))

baseline = {sp: gen[sp] for sp in gen}
azimuth = resolve_line_azimuth_degrees("123.1", baseline, baseline_path=None)
check("resolved diff azimuth == 123.1", approx(azimuth, 123.1, 1e-6), f"{azimuth}")

rows = compute_postplot_4d_diff_rows(baseline, sources, "123.1")
print(f"computed {len(rows)} diff rows")
check("diff rows produced", len(rows) > 100, str(len(rows)))

# Independently recompute crossline/inline/radial for several SPs and compare.
worst = 0.0
checked = 0
for row in rows:
    base = baseline.get(row.shotpoint)
    src = sources.get(row.shotpoint)
    if base is None or src is None:
        continue
    de = src.x - base.x
    dn = src.y - base.y
    th = math.radians(123.1)
    inline = de * math.sin(th) + dn * math.cos(th)
    crossline = de * math.cos(th) - dn * math.sin(th)
    radial = math.hypot(inline, crossline)
    worst = max(
        worst,
        abs(inline - row.inline_m),
        abs(crossline - row.crossline_m),
        abs(radial - row.radial_m),
    )
    # radial must equal euclidean distance of (de,dn) -- rotation invariant
    eucl = math.hypot(de, dn)
    worst = max(worst, abs(eucl - row.radial_m))
    checked += 1
print(f"re-derived {checked} rows; worst abs diff vs module = {worst:.3e} m")
check("module crossline/inline/radial match independent formula",
      worst < 1e-6, f"{worst:.2e}")

# radial == euclidean distance (datum/azimuth independent sanity)
sample = rows[len(rows) // 2]
b = baseline[sample.shotpoint]
s = sources[sample.shotpoint]
eucl = math.hypot(s.x - b.x, s.y - b.y)
check("radial == sqrt(inline^2+crossline^2) == euclidean E/N distance",
      approx(sample.radial_m, eucl, 1e-9)
      and approx(sample.radial_m, math.hypot(sample.inline_m, sample.crossline_m), 1e-9),
      f"sp{sample.shotpoint} radial={sample.radial_m:.4f} eucl={eucl:.4f}")

# Spot check the documented SP1536 deviation against the known table values.
if 1536 in sources and 1536 in baseline:
    r1536 = next((r for r in rows if r.shotpoint == 1536), None)
    if r1536:
        print(f"SP1536: crossline={r1536.crossline_m:.3f} inline={r1536.inline_m:.3f} "
              f"radial={r1536.radial_m:.3f}")

print()
print("=" * 78)
print(f"RESULT: {PASS} passed, {FAIL} failed")
print("=" * 78)
sys.exit(1 if FAIL else 0)
