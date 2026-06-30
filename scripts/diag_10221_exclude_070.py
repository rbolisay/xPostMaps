"""Diagnose excluded shotpoints on 10221 / 1065P1A-070.a070 (navplan baseline)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xpostmaps.core.database import Database
from xpostmaps.core.postplot_4d_matching import build_postplot_4d_rows
from xpostmaps.core.postplot_4d_diff import calculate_match_diff_rows
from xpostmaps.core.postplot_4d_plot_data import SequenceDiffSet, build_plot_series
from xpostmaps.core.postplot_4d_survey_spec import (
    Severity,
    StatType,
    SurveySpecRow,
    evaluate_survey_specs,
    flag_map_for_kind,
    parse_excluded_shotpoints,
    _flagged_points_by_source,
)

DB = ROOT / "data" / "10221.db"


def main() -> int:
    db = Database(DB)
    settings, map_data = db.load_project("10221", with_positions=True)
    settings.postplot_4d_baseline = "navplan"
    positions = db.load_positions("10221")
    rows = build_postplot_4d_rows(map_data, settings, "navplan")
    match = next(r for r in rows if r.sequence_id.startswith("70.1065P1A-070.a070.p190"))
    diff_rows = db.load_postplot_4d_diffs("10221", match.baseline_kind, match.sequence_id)
    if not diff_rows:
        diff_rows = calculate_match_diff_rows(
            map_data, settings, positions, match, database=db, project_name="10221"
        )
    ds = SequenceDiffSet(match_row=match, diff_rows=diff_rows)

    print(f"sequence_no={match.sequence_no!r} fsp={match.first_sp} lsp={match.last_sp}")
    print(f"baseline={match.baseline_kind} diff_rows={len(diff_rows)}")

    excl_text = "1481-1461"
    excl = parse_excluded_shotpoints(excl_text)
    print(f"excluded: {len(excl)} SPs, range {min(excl)}-{max(excl)}")

    specs = [
        SurveySpecRow(
            statistic=StatType.MAX_VALUE,
            metric="radial",
            stat_value=12.0,
            absolute=True,
            severity=Severity.WARNING,
        ),
        SurveySpecRow(
            statistic=StatType.MAX_CONSECUTIVE_FAILED,
            metric="radial",
            reference_value=10.0,
            stat_value=8.0,
            severity=Severity.ERROR,
        ),
        SurveySpecRow(
            statistic=StatType.MAX_PCT_FAILURE,
            metric="radial",
            reference_value=7.5,
            stat_value=10.0,
            severity=Severity.ERROR,
        ),
    ]

    for label, emap in [
        ("no exclusion", {}),
        ("key 070", {"070": excl_text}),
        ("key 70 (alias)", {"70": excl_text}),
    ]:
        flags = flag_map_for_kind([ds], specs, "radial", excluded_by_sequence=emap)
        all_sp = sorted({sp for bucket in flags.values() for sp in bucket})
        in_excl = [sp for sp in all_sp if sp in excl]
        out_excl = [sp for sp in all_sp if sp not in excl]
        ev = evaluate_survey_specs([ds], specs, excluded_by_sequence=emap)
        print(f"\n--- {label} --- acceptance={ev.accepted} warn={ev.has_warning}")
        print(f"  failed_details={len(ev.failed_details)} flagged={len(all_sp)}")
        if in_excl:
            print(f"  BUG flagged inside excluded: {in_excl}")
        if out_excl:
            print(f"  flagged outside excluded: {out_excl}")
        for src in ("G01", "G02"):
            bucket = flags.get(src, {})
            if bucket:
                print(f"  {src} flags: {dict(sorted(bucket.items()))}")

    series = build_plot_series(diff_rows, match, "radial", "G01")
    sp_to_val = dict(zip(series.shotpoints, series.values, strict=False))
    print("\n--- G01 radial around peak ---")
    for sp in range(1455, 1486, 2):
        if sp in sp_to_val:
            print(f"  SP {sp}: {sp_to_val[sp]:.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
