"""Dedicated parser for preplot and navplan files (xSeisVision-compatible)."""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from xpostmaps.core.models import LineSegment, PositionRecord, RecordType
from xpostmaps.parsers.metadata_parser import parse_file_metadata
from xpostmaps.utils.numba_accel import infer_line_direction

PREPLOT_EXTENSIONS = {
    ".p111",
    ".p190",
    ".P111",
    ".P190",
    ".nav",
    ".navplan",
    ".plan",
    ".txt",
}

NAVPLAN_EXTENSIONS = {".nav", ".navplan", ".plan"}

_V_RECORD_RE = re.compile(
    r"^V(?P<line>[A-Za-z0-9_]+)\s+"
    r"(?P<shotpoint>\d{4,6})"
    r"(?P<latdeg>\d{2})(?P<latmin>\d{2})(?P<latsec>\d{2}\.\d{2})(?P<lathem>[NS])"
    r"(?P<londeg>\d{3})(?P<lonmin>\d{2})(?P<lonsec>\d{2}\.\d{2})(?P<lonhem>[EW])\s*"
    r"(?P<easting>\d{4,8}\.\d)(?P<northing>\d{5,10}\.\d)"
)

_S_PREPLOT_LAT_RE = re.compile(r"^(\d{1,6})\s*(\d{6}\.\d{2}[NS])")
_S_PREPLOT_LAT_TIGHT_RE = re.compile(r"^(\d{1,6})(\d{6}\.\d{2}[NS])")
_S_LON_RE = re.compile(r"(\d{6}\.\d{2}[EW])\s+(.+)")
_S_LON_TIGHT_RE = re.compile(r"(\d{6}\.\d{2}[EW])(.+)")
_EN_PAIR_RE = re.compile(r"(\d+\.\d)(\d+\.\d)")


@dataclass
class _P111Line:
    line_name: str = ""
    fsp: str = ""
    lsp: str = ""
    path_points: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class PreplotParseResult:
    segments: list[LineSegment]
    records: list[PositionRecord]
    metadata: dict[str, str]
    kind: str  # preplot | dogleg | navplan


def _to_float(value: str) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return float("nan")


def _append_unique_point(points: list[tuple[float, float]], easting: str, northing: str) -> None:
    x = _to_float(easting)
    y = _to_float(northing)
    if not (x == x and y == y):
        return
    candidate = (x, y)
    if not points or points[-1] != candidate:
        points.append(candidate)


def _is_navplan_file(path: Path) -> bool:
    if path.suffix.lower() in NAVPLAN_EXTENSIONS:
        return True
    name = path.name.lower()
    return "navplan" in name


def detect_preplot_format(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".p111":
        return "p111"
    if suffix == ".p190":
        return "p190"
    if suffix in NAVPLAN_EXTENSIONS:
        return "navplan"
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for _ in range(30):
            line = handle.readline()
            if not line:
                break
            if line.startswith("N1,"):
                return "p111"
            if line.startswith("HC,"):
                return "p111"
            if line.startswith("H") and ":" not in line[:20]:
                if line.startswith("V") or "SURVEY" in line:
                    return "p190"
            if line.startswith("V") and len(line) > 40:
                return "p190"
    return "p190"


def _parse_p111_preplot_file(path: Path) -> tuple[list[LineSegment], list[PositionRecord], str]:
    file_name = path.name
    lines: list[_P111Line] = []
    current: _P111Line | None = None
    records: list[PositionRecord] = []

    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if not row:
                continue
            record_type = row[0].strip()
            if record_type != "N1" or len(row) < 2:
                continue
            subtype = row[1].strip()
            if subtype == "0" and len(row) >= 7:
                if current and current.path_points:
                    lines.append(current)
                current = _P111Line(
                    line_name=row[4].strip(),
                    fsp=row[5].strip(),
                    lsp=row[6].strip(),
                )
            elif subtype == "2" and current is not None and len(row) >= 17:
                _append_unique_point(current.path_points, row[8], row[9])
                _append_unique_point(current.path_points, row[15], row[16])

    if current and current.path_points:
        lines.append(current)

    segments: list[LineSegment] = []
    max_points = 0
    for line in lines:
        max_points = max(max_points, len(line.path_points))
        xs = [p[0] for p in line.path_points]
        ys = [p[1] for p in line.path_points]
        try:
            fsp = int(float(line.fsp))
            lsp = int(float(line.lsp))
        except ValueError:
            fsp, lsp = 0, 0
        pnums = np.array(
            [fsp + i * max(1, (lsp - fsp) // max(len(line.path_points) - 1, 1))
             for i in range(len(line.path_points))]
            if fsp and lsp and len(line.path_points) > 1
            else np.arange(len(line.path_points), dtype=np.int64),
            dtype=np.int64,
        )
        for idx, (x, y) in enumerate(line.path_points):
            sp = int(pnums[idx]) if idx < len(pnums) else idx
            records.append(
                PositionRecord(
                    file_name=file_name,
                    record_type=RecordType.PREPLOT,
                    line_name=line.line_name,
                    vessel_id="",
                    source_id="",
                    point_num=sp,
                    x=x,
                    y=y,
                )
            )
        direction = infer_line_direction(pnums) if len(pnums) > 1 else 1
        segments.append(
            LineSegment(
                line_name=line.line_name,
                record_type=RecordType.PREPLOT,
                xs=xs,
                ys=ys,
                direction=direction,
                file_name=file_name,
                sequence_no=line.fsp,
                line_direction="",
            )
        )

    if max_points >= 5:
        kind = "navplan"
    elif max_points > 2:
        kind = "dogleg"
    else:
        kind = "preplot"
    return segments, records, kind


def _parse_p190_v_record(line: str) -> dict | None:
    match = _V_RECORD_RE.match(line.strip())
    if not match:
        return None
    return {
        "line_name": match.group("line"),
        "shotpoint": match.group("shotpoint"),
        "easting": _to_float(match.group("easting")),
        "northing": _to_float(match.group("northing")),
    }


def _parse_p190_s_record_preplot(line: str) -> dict | None:
    if len(line) < 55 or not line.startswith("S"):
        return None
    line_name = line[1:13].strip()
    if not line_name:
        return None
    remainder = line[19:].lstrip()
    sp_lat_match = _S_PREPLOT_LAT_RE.match(remainder) or _S_PREPLOT_LAT_TIGHT_RE.match(remainder)
    if not sp_lat_match:
        return None
    shotpoint = sp_lat_match.group(1)
    after_lat = remainder[sp_lat_match.end() :].lstrip()
    lon_match = _S_LON_RE.match(after_lat) or _S_LON_TIGHT_RE.match(after_lat)
    if not lon_match:
        return None
    after_lon = lon_match.group(2).strip()
    en_match = _EN_PAIR_RE.search(after_lon)
    if en_match:
        easting = _to_float(en_match.group(1))
        northing = _to_float(en_match.group(2))
    else:
        parts = re.findall(r"\d+\.\d+", after_lon)
        if len(parts) < 2:
            return None
        easting = _to_float(parts[0])
        northing = _to_float(parts[1])
    if not (easting == easting and northing == northing):
        return None
    return {
        "line_name": line_name,
        "shotpoint": shotpoint,
        "easting": easting,
        "northing": northing,
    }


def _points_to_segment(
    file_name: str,
    line_name: str,
    points: list[dict],
    record_type: RecordType,
) -> tuple[LineSegment, list[PositionRecord]]:
    xs = [p["easting"] for p in points]
    ys = [p["northing"] for p in points]
    pnums = []
    records: list[PositionRecord] = []
    for p in points:
        try:
            sp = int(p["shotpoint"])
        except (ValueError, TypeError):
            sp = 0
        pnums.append(sp)
        records.append(
            PositionRecord(
                file_name=file_name,
                record_type=record_type,
                line_name=line_name,
                vessel_id="",
                source_id="",
                point_num=sp,
                x=p["easting"],
                y=p["northing"],
            )
        )
    direction = infer_line_direction(np.array(pnums, dtype=np.int64)) if pnums else 1
    segment = LineSegment(
        line_name=line_name,
        record_type=record_type,
        xs=xs,
        ys=ys,
        direction=direction,
        file_name=file_name,
    )
    return segment, records


def _parse_p190_preplot_file(path: Path) -> tuple[list[LineSegment], list[PositionRecord], str]:
    file_name = path.name
    line_points_v: dict[str, list[dict]] = defaultdict(list)
    line_points_s: dict[str, list[dict]] = defaultdict(list)

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n\r")
            if not line:
                continue
            if line.startswith("S") and len(line) >= 55:
                parsed = _parse_p190_s_record_preplot(line)
                if parsed:
                    line_points_s[parsed["line_name"]].append(parsed)
            elif line.startswith("V"):
                parsed = _parse_p190_v_record(line)
                if parsed:
                    line_points_v[parsed["line_name"]].append(parsed)

    use_s = bool(line_points_s)
    points_by_line = line_points_s if use_s else line_points_v
    segments: list[LineSegment] = []
    records: list[PositionRecord] = []
    max_points = 0

    for line_name in sorted(points_by_line.keys()):
        points = points_by_line[line_name]
        if len(points) < 2:
            continue
        max_points = max(max_points, len(points))
        seg, recs = _points_to_segment(file_name, line_name, points, RecordType.PREPLOT)
        segments.append(seg)
        records.extend(recs)

    if max_points >= 5:
        kind = "navplan"
    elif max_points > 2:
        kind = "dogleg"
    else:
        kind = "preplot"
    return segments, records, kind


def _parse_navplan_file(path: Path) -> tuple[list[LineSegment], list[PositionRecord], str]:
    file_name = path.name
    line_name = path.stem
    shotpoints: list[dict] = []

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n\r")
            if not line or not line.startswith("S"):
                continue
            parsed = _parse_p190_s_record_preplot(line)
            if parsed is None:
                continue
            if parsed["line_name"]:
                line_name = parsed["line_name"]
            shotpoints.append(parsed)

    shotpoints.sort(key=lambda item: int(item["shotpoint"]))
    segments: list[LineSegment] = []
    records: list[PositionRecord] = []
    if len(shotpoints) >= 2:
        seg, recs = _points_to_segment(
            file_name, line_name, shotpoints, RecordType.NAVPLAN
        )
        segments.append(seg)
        records.extend(recs)
    return segments, records, "navplan"


def parse_preplot_file(path: Path) -> PreplotParseResult:
    fmt = detect_preplot_format(path)
    if fmt == "p111":
        segments, records, kind = _parse_p111_preplot_file(path)
    elif fmt == "navplan":
        segments, records, kind = _parse_navplan_file(path)
    else:
        segments, records, kind = _parse_p190_preplot_file(path)

    metadata = parse_file_metadata(path, "p111" if fmt == "p111" else "p190")
    return PreplotParseResult(
        segments=segments,
        records=records,
        metadata=metadata,
        kind=kind,
    )


def parse_preplot_files(paths: list[Path]) -> tuple[list[LineSegment], dict[str, str], dict[str, int]]:
    all_segments: list[LineSegment] = []
    all_metadata: dict[str, str] = {}
    stats = {"preplot_files": 0, "navplan_files": 0, "preplot_lines": 0, "total_points": 0}

    for path in paths:
        result = parse_preplot_file(path)
        all_segments.extend(result.segments)
        for key, value in result.metadata.items():
            if key not in all_metadata or not all_metadata[key]:
                all_metadata[key] = value
        stats["preplot_files"] += 1
        if result.kind == "navplan":
            stats["navplan_files"] += 1
        stats["preplot_lines"] += len(result.segments)
        stats["total_points"] += len(result.records)

    return all_segments, all_metadata, stats


def resolve_preplot_files(settings) -> list[Path]:
    allowed_suffixes = {ext.lower() for ext in PREPLOT_EXTENSIONS}
    if getattr(settings, "preplot_files_explicit", False):
        return sorted(Path(f) for f in settings.preplot_files if Path(f).is_file())
    if settings.preplot_files:
        files = [Path(f) for f in settings.preplot_files if Path(f).is_file()]
        if files:
            return sorted(files)
    for dir_attr in ("preplots_dir", "overlay_dir", "p111_p190_dir"):
        folder = getattr(settings, dir_attr, "") or ""
        if not folder:
            continue
        root = Path(folder)
        if root.is_dir():
            found = sorted(
                p for p in root.rglob("*")
                if p.is_file() and p.suffix.lower() in allowed_suffixes
            )
            if found:
                return found
    return []
