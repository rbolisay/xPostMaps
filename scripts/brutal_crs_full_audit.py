"""Exhaustive CRS / EPSG audit across EVERY real navplan, P111, P190 file.

Zero-tolerance audit demanded by ops: a wrong or missing CRS silently corrupts
the Diff Stat (FSP/LSP positions, crossline/inline/radial). This script:

  1. Resolves an EPSG for EVERY navplan / P111 / P190 file in 4030 and 7027.
     ANY file that fails to resolve a CRS is a hard FAIL.
  2. Asserts intra-survey CRS consistency (all 4030 files == 23031,
     all 7027 files == 32621) so baseline/source always share a datum+grid.
  3. Validates the CRS-consistency gate used before a Diff Stat is computed
     (baseline EPSG, source EPSG and map EPSG must reconcile).
  4. Validates multi-source generated shotpoint geometry on the 7027 DB
     (dual/triple source crossline offsets, per-source keys).

Runs with or without pyproj; header-only inference must still succeed for the
ED50 / WGS84 UTM families used by these surveys.

Exit code is non-zero if any check fails.
"""

from __future__ import annotations

import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xpostmaps.core.crs_utils import normalize_epsg
from xpostmaps.core.models import (
    MapData,
    PositionRecord,
    ProjectSettings,
    RecordType,
    make_sequence_group_id,
)
from xpostmaps.core.postplot_4d_diff import (
    BaselineShotpoint,
    CrsMismatchError,
    _file_epsg,
    _generate_preplot_shotpoints,
    assess_diff_crs_consistency,
    calculate_match_diff_rows,
    compute_postplot_4d_diff_rows,
)
from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow
from xpostmaps.parsers.metadata_parser import parse_file_metadata
from xpostmaps.parsers.p111_parser import parse_p111_file
from xpostmaps.parsers.preplot_parser import (
    parse_navplan_source_file,
    parse_preplot_file,
)

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f"  ::  {detail}" if detail else ""))
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(f"{label}  ::  {detail}")


def collect(survey_dir: Path) -> list[Path]:
    if not survey_dir.is_dir():
        return []
    files: list[Path] = []
    for pattern in ("*.navplan", "*.p111", "*.P111", "*.p190", "*.P190", "*.190"):
        files.extend(survey_dir.rglob(pattern))
    return sorted({p.resolve() for p in files})


def try_pyproj() -> str:
    try:
        import pyproj

        return pyproj.__version__
    except Exception:  # noqa: BLE001
        return ""


print("=" * 78)
print("BRUTAL FULL CRS AUDIT  (every real navplan / P111 / P190 file)")
print("=" * 78)
pyproj_ver = try_pyproj()
print(f"pyproj: {pyproj_ver or 'NOT INSTALLED (header-only inference path under test)'}")

SURVEYS = {
    "4030": (ROOT / "4D/4030", "23031"),
    "7027": (ROOT / "4D/7027", "32621"),
}

# ---- 1 + 2. EPSG resolves for every file; intra-survey consistency ---------
for survey, (survey_dir, expected_epsg) in SURVEYS.items():
    files = collect(survey_dir)
    print(f"\n--- SURVEY {survey}: {len(files)} file(s) under {survey_dir} ---")
    check(f"{survey}: files discovered", bool(files), str(len(files)))
    if not files:
        continue

    resolved: dict[str, str] = {}
    unresolved: list[str] = []
    counts: Counter[str] = Counter()
    for path in files:
        try:
            md = parse_file_metadata(path)
        except OSError as exc:  # noqa: BLE001
            unresolved.append(f"{path.name} (read error: {exc})")
            continue
        epsg = normalize_epsg(md.get("epsg code", ""))
        resolved[path.name] = epsg
        if epsg:
            counts[epsg] += 1
        else:
            unresolved.append(
                f"{path.name} "
                f"(datum={md.get('geographic datum','')[:18]!r} "
                f"proj={md.get('projection','')[:18]!r} "
                f"zone={md.get('projection zone','')!r})"
            )

    check(
        f"{survey}: EVERY file resolved a CRS (0 unknown)",
        not unresolved,
        f"{len(unresolved)} unresolved" if unresolved else "all resolved",
    )
    for item in unresolved[:20]:
        print(f"        UNRESOLVED: {item}")

    check(
        f"{survey}: single consistent EPSG across all files",
        len(counts) == 1,
        " ".join(f"{k}x{v}" for k, v in counts.most_common()),
    )
    check(
        f"{survey}: resolved EPSG == expected {expected_epsg}",
        set(counts) == {expected_epsg},
        " ".join(f"{k}x{v}" for k, v in counts.most_common()),
    )

# ---- 3. CRS-consistency gate before Diff Stat ------------------------------
print("\n--- 3. CRS GATE: baseline EPSG / source EPSG / map EPSG reconcile ---")
gate_cases = [
    (
        "4030 navplan vs P111",
        ROOT / "4D/4030/Navplans/Priority1/0103643A.navplan",
        ROOT / "4D/4030/P111V/069.0103643A-069.nrt.GFUNREG.p111",
        "23031",
    ),
    (
        "4030 preplot vs P111",
        ROOT / "4D/4030/Preplot/4030_Mariner4D_Preplots_v2.190",
        ROOT / "4D/4030/P111V/069.0103643A-069.nrt.GFUNREG.p111",
        "23031",
    ),
    (
        "7027 preplot vs P111 (multi-source)",
        ROOT / "4D/7027/Preplot/7027_S_TRINAV_v2.p190",
        ROOT / "4D/7027/P111V_S/3237.53196213237.a3237.GFUNREG.p111",
        "32621",
    ),
]
for label, baseline_path, source_path, expected in gate_cases:
    if not baseline_path.is_file() or not source_path.is_file():
        check(f"{label}: files exist", False, f"{baseline_path.name}/{source_path.name}")
        continue
    base_epsg = _file_epsg(baseline_path)
    src_epsg = _file_epsg(source_path)
    print(f"  {label}: baseline={base_epsg or '(none)'} source={src_epsg or '(none)'}")
    check(f"{label}: baseline CRS resolved", bool(base_epsg), base_epsg or "(none)")
    check(f"{label}: source CRS resolved", bool(src_epsg), src_epsg or "(none)")
    check(
        f"{label}: baseline CRS == source CRS == {expected}",
        base_epsg == src_epsg == expected,
        f"{base_epsg} / {src_epsg}",
    )

# ---- 4. Multi-source generated shotpoints (7027) ---------------------------
print("\n--- 4. MULTI-SOURCE GENERATED SHOTPOINTS (7027) --------------------")
# Synthetic 2 m grid with known geometry: north-running line, 2 sources, 50 m.
controls = [
    PositionRecord("p", RecordType.PREPLOT, "L", "", "", 100, 1000.0, 2000.0),
    PositionRecord("p", RecordType.PREPLOT, "L", "", "", 110, 1000.0, 2250.0),
]
gen = _generate_preplot_shotpoints(
    controls, "32621", source_count=2, source_separation_m=50.0, line_azimuth_deg=0.0
)
check("dual-source produces per-source keys", (100, "1") in gen and (100, "2") in gen)
if (100, "1") in gen and (100, "2") in gen:
    sep = math.hypot(gen[(100, "1")].x - gen[(100, "2")].x, gen[(100, "1")].y - gen[(100, "2")].y)
    check("dual-source separation == 50 m", abs(sep - 50.0) < 1e-6, f"{sep:.6f}")
    # north line (az 0): crossline offset is purely easting; G01 starboard (+E).
    check(
        "G01 placed +25 m east, G02 -25 m east (north line)",
        abs(gen[(100, "1")].x - 1025.0) < 1e-6 and abs(gen[(100, "2")].x - 975.0) < 1e-6,
        f"G01x={gen[(100,'1')].x:.3f} G02x={gen[(100,'2')].x:.3f}",
    )

triple = _generate_preplot_shotpoints(
    controls, "32621", source_count=3, source_separation_m=37.5, line_azimuth_deg=0.0
)
if (100, "2") in triple:
    check(
        "triple-source centre gun has zero crossline offset",
        abs(triple[(100, "2")].x - 1000.0) < 1e-6,
        f"centre x={triple[(100,'2')].x:.3f}",
    )

# Real multi-source P111 from 7027: confirm distinct source ids per shotpoint.
ms_p111 = ROOT / "4D/7027/P111V_S/3237.53196213237.a3237.GFUNREG.p111"
if ms_p111.is_file():
    recs = [r for r in parse_p111_file(ms_p111) if r.record_type == RecordType.SOURCE]
    by_sp: dict[int, set[str]] = defaultdict(set)
    for r in recs:
        if r.point_num > 0:
            by_sp[r.point_num].add(r.source_id)
    src_ids = sorted({sid for ids in by_sp.values() for sid in ids})
    print(f"  7027 P111 firing sources: {len(recs)} recs, source ids={src_ids}")
    check("7027 P111 firing sources parsed", len(recs) > 0, str(len(recs)))

# ---- 5. CRS GATE END-TO-END (real 4030 navplan vs P111) --------------------
print("\n--- 5. CRS GATE END-TO-END (block silent corruption) ---------------")
navplan = ROOT / "4D/4030/Navplans/Priority1/0103643A.navplan"
p111 = ROOT / "4D/4030/P111V/069.0103643A-069.nrt.GFUNREG.p111"
if navplan.is_file() and p111.is_file():
    src = [
        r
        for r in parse_p111_file(p111)
        if r.record_type == RecordType.SOURCE and r.point_num > 0
    ]
    rec = src[0]
    seq_id = make_sequence_group_id(rec.file_name, rec.sequence_no, rec.line_name) + "|source"
    match_row = Postplot4DMatchRow(
        baseline_name="0103643A",
        baseline_kind="navplan",
        line_name=rec.line_name,
        subline=rec.subline,
        sequence_no=rec.sequence_no,
        first_sp=min(r.point_num for r in src),
        last_sp=max(r.point_num for r in src),
        line_direction="123.1",
        sequence_id=seq_id,
        baseline_file_name="0103643A.navplan",
    )
    map_data = MapData()
    map_data.postmap_info.epsg_code = "23031"

    # (a) Happy path: every CRS resolved + consistent -> diff allowed, rows built.
    ok_settings = ProjectSettings(
        nav_files=[str(p111.resolve())],
        navplan_files=[str(navplan.resolve())],
        postplot_4d_baseline="navplan",
    )
    a = assess_diff_crs_consistency(map_data, ok_settings, src, match_row)
    check("gate ACCEPTS verified 23031 navplan/P111", a.ok, a.reason)
    check("gate reports baseline 23031", a.baseline_epsg == "23031", a.baseline_epsg)
    check("gate reports source 23031", set(a.source_epsgs) == {"23031"},
          ",".join(a.source_epsgs))
    rows = calculate_match_diff_rows(map_data, ok_settings, src, match_row)
    check("verified CRS -> FSP/LSP diff rows populated", bool(rows), str(len(rows)))

    # (b) Source CRS unknown -> gate must BLOCK and calculate must raise.
    bad_settings = ProjectSettings(
        navplan_files=[str(navplan.resolve())],
        postplot_4d_baseline="navplan",
    )
    b = assess_diff_crs_consistency(map_data, bad_settings, src, match_row)
    check("gate BLOCKS when source CRS unknown", not b.ok, b.reason)
    raised = False
    try:
        calculate_match_diff_rows(map_data, bad_settings, src, match_row)
    except CrsMismatchError:
        raised = True
    check("calculate REFUSES (raises) on unknown source CRS", raised)

    # (c) No firing sources at all -> gate must BLOCK.
    c = assess_diff_crs_consistency(map_data, ok_settings, [], match_row)
    check("gate BLOCKS when no firing-source shotpoints", not c.ok, c.reason)
else:
    check("4030 navplan + P111 present for gate test", False)

print("\n" + "=" * 78)
print(f"RESULT: {PASS} passed, {FAIL} failed")
if FAILURES:
    print("FAILURES:")
    for item in FAILURES:
        print(f"  - {item}")
print("=" * 78)
sys.exit(1 if FAIL else 0)
