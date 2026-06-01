"""Parse Survey Perimeter / Survey Polygon from preplot P111 and P190 files."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from xpostmaps.core.models import SurveyPerimeter

_P111_PERIMETER_HEADER = "Survey Perimeter Definition"
_P190_POLYGON_MARKER = "SURVEY POLYGON"

_P190_POINT_RE = re.compile(
    r"^P(?P<idx>\d+)\s+"
    r"N\s+(?P<latd>\d+)\s+(?P<latm>\d+)\s+(?P<lats>[\d.]+)\s+"
    r"W\s+(?P<lond>\d+)\s+(?P<lonm>\d+)\s+(?P<lons>[\d.]+)\s+"
    r"(?P<easting>[\d.]+)mE\s+(?P<northing>[\d.]+)mN",
    re.IGNORECASE,
)

_P111_M1_PREFIX = ("M1", "0", "1", "1")
_P111_EASTING_IDX = 6
_P111_NORTHING_IDX = 7
_P111_LAT_IDX = 9
_P111_LON_IDX = 10


def _to_float(value: str) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return float("nan")


def _field(parts: list[str], index: int) -> str:
    if index < 0 or index >= len(parts):
        return ""
    return parts[index].strip()


def _dms_to_decimal(deg: str, minutes: str, seconds: str, hemisphere: str) -> str:
    try:
        value = float(deg) + float(minutes) / 60.0 + float(seconds) / 3600.0
        if hemisphere.upper() in ("S", "W"):
            value = -value
        return f"{value:.8f}"
    except (ValueError, TypeError):
        return ""


def _close_polygon(xs: list[float], ys: list[float]) -> tuple[list[float], list[float]]:
    if len(xs) < 2:
        return xs, ys
    if xs[0] != xs[-1] or ys[0] != ys[-1]:
        return xs + [xs[0]], ys + [ys[0]]
    return xs, ys


def parse_p111_survey_perimeter(path: Path) -> SurveyPerimeter | None:
    """Parse M1 records following a Survey Perimeter Definition header."""
    file_name = path.name
    in_perimeter = False
    perimeter_name = "Survey Perimeter"
    xs: list[float] = []
    ys: list[float] = []
    lats: list[str] = []
    lons: list[str] = []
    seen_points: set[tuple[float, float]] = set()

    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if not row:
                continue
            record = row[0].strip()
            joined = ",".join(row)

            if record == "H1" and _P111_PERIMETER_HEADER in joined:
                in_perimeter = True
                if len(row) > 6 and row[6].strip() and not row[6].strip().isdigit():
                    perimeter_name = row[6].strip()
                else:
                    for idx, part in enumerate(row):
                        if part.strip() == "1" and idx + 1 < len(row):
                            candidate = row[idx + 1].strip()
                            if candidate and not candidate.isdigit():
                                perimeter_name = candidate
                                break
                continue

            if not in_perimeter:
                continue

            if record == "N1" or (record == "H1" and _P111_PERIMETER_HEADER not in joined):
                break

            if record != "M1" or len(row) < 8:
                continue
            if tuple(p.strip() for p in row[:4]) != _P111_M1_PREFIX:
                continue

            x = _to_float(_field(row, _P111_EASTING_IDX))
            y = _to_float(_field(row, _P111_NORTHING_IDX))
            if not (x == x and y == y):
                continue

            key = (round(x, 3), round(y, 3))
            if key in seen_points and len(xs) >= 3:
                break
            seen_points.add(key)

            xs.append(x)
            ys.append(y)
            lats.append(_field(row, _P111_LAT_IDX))
            lons.append(_field(row, _P111_LON_IDX))

    if len(xs) < 3:
        return None

    xs, ys = _close_polygon(xs, ys)
    if lats and lats[0] != lats[-1]:
        lats.append(lats[0])
        lons.append(lons[0])

    return SurveyPerimeter(
        file_name=file_name,
        name=perimeter_name,
        xs=xs,
        ys=ys,
        latitudes=lats,
        longitudes=lons,
    )


def _strip_p190_prefix(line: str) -> str:
    text = line.strip()
    if text.startswith("H2600"):
        return text[5:].lstrip()
    if text.startswith("H"):
        return text[1:].lstrip()
    return text


def parse_p190_survey_perimeter(path: Path) -> SurveyPerimeter | None:
    """Parse P01..Pxx points inside the SURVEY POLYGON section."""
    file_name = path.name
    in_polygon = False
    xs: list[float] = []
    ys: list[float] = []
    lats: list[str] = []
    lons: list[str] = []

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.rstrip("\n\r")
            if not line.strip():
                continue

            upper = line.upper()
            if _P190_POLYGON_MARKER in upper:
                in_polygon = True
                continue

            if not in_polygon:
                continue

            if "<<<" in upper and _P190_POLYGON_MARKER not in upper:
                break
            if "ANCHOR POINT" in upper:
                break

            content = _strip_p190_prefix(line)
            match = _P190_POINT_RE.match(content)
            if not match:
                continue

            x = _to_float(match.group("easting"))
            y = _to_float(match.group("northing"))
            if not (x == x and y == y):
                continue

            lat = _dms_to_decimal(
                match.group("latd"),
                match.group("latm"),
                match.group("lats"),
                "N",
            )
            lon = _dms_to_decimal(
                match.group("lond"),
                match.group("lonm"),
                match.group("lons"),
                "W",
            )

            xs.append(x)
            ys.append(y)
            lats.append(lat)
            lons.append(lon)

    if len(xs) < 3:
        return None

    xs, ys = _close_polygon(xs, ys)
    if lats and (not lons or lats[0] != lats[-1]):
        lats.append(lats[0])
        lons.append(lons[0])

    return SurveyPerimeter(
        file_name=file_name,
        name="Survey Polygon",
        xs=xs,
        ys=ys,
        latitudes=lats,
        longitudes=lons,
    )


def parse_survey_perimeter(path: Path) -> SurveyPerimeter | None:
    suffix = path.suffix.lower()
    if suffix == ".p111":
        return parse_p111_survey_perimeter(path)
    if suffix == ".p190":
        return parse_p190_survey_perimeter(path)
    return None


def parse_survey_perimeters(paths: list[Path]) -> list[SurveyPerimeter]:
    perimeters: list[SurveyPerimeter] = []
    for path in paths:
        perimeter = parse_survey_perimeter(path)
        if perimeter is not None:
            perimeters.append(perimeter)
    return perimeters
