"""Extract postmap metadata from P111/P190/Navplan file headers."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from xpostmaps.core.crs_utils import infer_epsg_from_header, normalize_epsg
from xpostmaps.core.models import PostmapInfo, ProjectSettings
from xpostmaps.parsers.p190_parser import format_line_direction

EPSG_RE = re.compile(r"EPSG\s*[:\s]?\s*(\d+)", re.IGNORECASE)
H_NUM_PREFIX = re.compile(r"^\d+\s+")
TRAILING_INT_RE = re.compile(r"(\d+)\s*$")
TRAILING_FLOAT_RE = re.compile(r"([\d.]+)\s*$")


PROJECTION_KEYWORDS = (
    "UTM",
    "TRANSVERSE MERCATOR",
    "MERCATOR",
    "LAMBERT",
    "STEREOGRAPHIC",
    "GAUSS",
    "ALBERS",
    "POLYCONIC",
    "KROVAK",
    "CASSINI",
    "OBLIQUE MERCATOR",
    "NATIONAL GRID",
    "STATE PLANE",
)


def _is_projected_crs_name(name: str, type_name: str) -> bool:
    if type_name.strip().lower() == "projected":
        return True
    upper = name.upper()
    return any(keyword in upper for keyword in PROJECTION_KEYWORDS)


def _normalize_key(key: str) -> str:
    return re.sub(r"\s+", " ", key.strip().lower())


def _set_if_empty(target: dict[str, str], key: str, value: str) -> None:
    value = value.strip()
    if not value:
        return
    norm = _normalize_key(key)
    if norm not in target or not target[norm]:
        target[norm] = value


def _extract_epsg(*texts: str) -> str:
    for text in texts:
        if not text:
            continue
        match = EPSG_RE.search(text)
        if match:
            return match.group(1)
    return ""


def _apply_p111_hc_row(info: dict[str, str], row: list[str]) -> None:
    label = row[4].strip() if len(row) > 4 else ""
    if not label:
        return
    if label == "Project Name" and len(row) >= 7:
        _set_if_empty(info, "project name", row[6].strip())
    elif label == "Client" and len(row) >= 6:
        _set_if_empty(info, "client", row[5].strip())
    elif label == "Survey Description" and len(row) >= 8:
        _set_if_empty(info, "survey description", row[5].strip())
        if len(row) >= 8 and row[7].strip():
            _set_if_empty(info, "area", row[7].strip())
    elif label.startswith("CRS Number/EPSG Code"):
        # Two IOGP P1/11 row shapes share this label prefix:
        #   HC,1,3,0 "CRS Number/EPSG Code/Name/Source": epsg=row[6], name=row[7]
        #   HC,1,4,0 "CRS Number/EPSG Code/Type/Name"  : epsg=row[6], type=row[8], name=row[9]
        subtype = row[2].strip() if len(row) > 2 else ""
        if subtype == "3" and len(row) >= 8:
            epsg, crs_name, type_name = row[6].strip(), row[7].strip(), ""
        elif subtype == "4" and len(row) >= 10:
            epsg, crs_name, type_name = row[6].strip(), row[9].strip(), row[8].strip()
        else:
            return
        # Compound / vertical CRS rows carry no single usable EPSG; never let
        # their (often empty) EPSG clobber a valid projected horizontal CRS.
        if (
            not epsg.isdigit()
            or type_name.lower() in ("compound", "vertical")
            or "COMPOUND" in crs_name.upper()
        ):
            return
        if _is_projected_crs_name(crs_name, type_name):
            info["epsg code"] = epsg
            info["crs name"] = crs_name
            info["projection"] = crs_name
        else:
            _set_if_empty(info, "epsg code", epsg)
            _set_if_empty(info, "crs name", crs_name)
    elif label == "Geodetic Datum" and len(row) >= 7:
        _set_if_empty(info, "geographic datum", row[6].strip())
    elif label == "Ellipsoid" and len(row) >= 7:
        _set_if_empty(info, "spheroid", row[6].strip())
        if len(row) >= 8:
            _set_if_empty(info, "semi-major axis", row[7].strip())
        if len(row) >= 10:
            _set_if_empty(info, "inverse flattening", row[9].strip())


def parse_p111_metadata(path: Path) -> dict[str, str]:
    """Parse HC/H/CC header cards from a P111 preplot file."""
    info: dict[str, str] = {}
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if not row:
                continue
            record_type = row[0].strip()
            if record_type in ("N1", "P1", "S1", "R1", "V1"):
                break
            if record_type == "HC":
                _apply_p111_hc_row(info, row)
            elif record_type == "H," or (record_type == "H" and len(row) > 1):
                if len(row) >= 6:
                    _set_if_empty(info, row[4] if len(row) > 4 else row[1], row[5])
            elif record_type == "CC" and len(row) > 4:
                text = row[4].strip()
                if "LINE-DIRECTION" in text.upper().replace(" ", ""):
                    match = TRAILING_FLOAT_RE.search(text)
                    if match:
                        formatted = format_line_direction(match.group(1))
                        if formatted:
                            _set_if_empty(info, "line direction", formatted)
                elif text.startswith("HEADING"):
                    match = TRAILING_FLOAT_RE.search(text)
                    if match:
                        _set_if_empty(info, "line heading", match.group(1))
                        formatted = format_line_direction(match.group(1))
                        if formatted:
                            _set_if_empty(info, "line direction", formatted)
                elif text.startswith("CRS EPSG Code"):
                    match = TRAILING_INT_RE.search(text)
                    if match:
                        _set_if_empty(info, "epsg code", match.group(1))
    epsg = _extract_epsg(
        info.get("epsg code", ""),
        info.get("crs name", ""),
        info.get("coordinate reference system", ""),
    )
    if epsg:
        _set_if_empty(info, "epsg code", epsg)
    elif not info.get("epsg code"):
        # No explicit EPSG: infer from datum + projection/CRS name + zone, the
        # same fallback used for P190 headers. The projected CRS name (e.g.
        # "WGS 84 / UTM zone 21N") usually carries enough to resolve a code.
        central_meridian, false_easting, false_northing, scale_factor = (
            _p190_grid_parameters(info)
        )
        inferred = infer_epsg_from_header(
            info.get("geographic datum", ""),
            info.get("projection", "") or info.get("crs name", ""),
            info.get("projection zone", ""),
            central_meridian=central_meridian,
            false_easting=false_easting,
            false_northing=false_northing,
            scale_factor=scale_factor,
        )
        if inferred:
            _set_if_empty(info, "epsg code", inferred)
            _set_if_empty(info, "crs name", f"EPSG:{inferred}")
    return info


def _p190_value(line: str) -> str:
    return line[32:].strip() if len(line) > 32 else line.strip()


def _parse_p190_central_meridian_deg(text: str) -> float | None:
    """Parse a central meridian in DMS (spaced or packed) or decimal degrees.

    Handles the common P190 spellings:
      * spaced DMS:   ``173 0 0.000E`` / ``  3 0 0.000E``
      * packed DMS:   ``0570000.000W`` (DDDMMSS.sss)
      * decimal:      ``57.0W`` / ``-57.0``
    """
    raw = (text or "").upper().strip()
    if not raw:
        return None

    hemisphere = ""
    if raw.endswith("E") or raw.endswith("W"):
        hemisphere = raw[-1]
        raw = raw[:-1].strip()

    degrees: float | None = None

    spaced = re.match(r"^\s*(\d{1,3})\s+(\d{1,2})\s+([\d.]+)\s*$", raw)
    if spaced:
        deg = float(spaced.group(1))
        minutes = float(spaced.group(2))
        seconds = float(spaced.group(3))
        degrees = deg + minutes / 60.0 + seconds / 3600.0
    elif re.fullmatch(r"\d{5,9}(?:\.\d+)?", raw):
        # Packed DDDMMSS.sss: seconds = last 2 integer digits, minutes = next 2.
        int_part, _, frac_part = raw.partition(".")
        seconds = float(int_part[-2:]) + (float(f"0.{frac_part}") if frac_part else 0.0)
        minutes = float(int_part[-4:-2] or 0)
        deg = float(int_part[:-4] or 0)
        degrees = deg + minutes / 60.0 + seconds / 3600.0
    else:
        match = re.search(r"[-+]?\d+(?:\.\d+)?", raw)
        if match:
            degrees = float(match.group(0))

    if degrees is None:
        return None
    if hemisphere == "W" and degrees > 0:
        degrees = -degrees
    return degrees


def _parse_p190_grid_origin(text: str) -> tuple[float | None, float | None]:
    match = re.search(
        r"([\d.]+)\s*E\s*([\d.]+)\s*N",
        (text or "").upper().replace(",", ""),
    )
    if not match:
        return None, None
    try:
        return float(match.group(1)), float(match.group(2))
    except ValueError:
        return None, None


def _parse_p190_scale_factor(text: str) -> float | None:
    match = re.search(r"([\d.]+)", text or "")
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _p190_grid_parameters(info: dict[str, str]) -> tuple[float | None, float | None, float | None, float | None]:
    central_meridian = _parse_p190_central_meridian_deg(
        info.get("central meridian", "")
        or info.get("long. of centr. merid.", "")
    )
    false_easting, false_northing = _parse_p190_grid_origin(
        info.get("grid coord at origin", "")
        or info.get("grid coord. at origin", "")
    )
    scale_factor = _parse_p190_scale_factor(
        info.get("scale factor", "")
    )
    return central_meridian, false_easting, false_northing, scale_factor


def parse_p190_metadata(path: Path) -> dict[str, str]:
    """Parse H records from a P190 preplot file."""
    info: dict[str, str] = {}
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.startswith("H"):
                if line.startswith(("S", "V", "E", "R", "P")):
                    break
                continue
            if line.startswith("H0100"):
                value = _p190_value(line)
                if "SURVEY AREA" in line[:32].upper():
                    _set_if_empty(info, "area", value)
                else:
                    _set_if_empty(info, "project name", value)
            elif line.startswith("H0200"):
                _set_if_empty(info, "date", _p190_value(line))
            elif line.startswith("H0300"):
                _set_if_empty(info, "client", _p190_value(line))
            elif line.startswith("H0400"):
                _set_if_empty(info, "geophysical contractor", _p190_value(line))
            elif line.startswith("H0500"):
                _set_if_empty(info, "positioning contractor", _p190_value(line))
            elif line.startswith("H1400"):
                value = _p190_value(line)
                parts = value.split()
                if value:
                    _set_if_empty(info, "geographic datum", value)
                if parts and len(parts) >= 2:
                    _set_if_empty(info, "spheroid", parts[1])
            elif line.startswith("H1800"):
                _set_if_empty(info, "projection", _p190_value(line))
            elif line.startswith("H1900"):
                _set_if_empty(info, "projection zone", _p190_value(line))
            elif line.startswith("H2200"):
                _set_if_empty(info, "central meridian", _p190_value(line))
            elif line.startswith("H2302"):
                _set_if_empty(info, "grid coord at origin", _p190_value(line))
            elif line.startswith("H2401"):
                _set_if_empty(info, "scale factor", _p190_value(line))
            elif "CRS EPSG Code" in line:
                match = TRAILING_INT_RE.search(line)
                if match:
                    _set_if_empty(info, "epsg code", match.group(1))
            elif "LINE-DIRECTION" in line.upper().replace(" ", ""):
                match = TRAILING_FLOAT_RE.search(line)
                if match:
                    formatted = format_line_direction(match.group(1))
                    if formatted:
                        _set_if_empty(info, "line direction", formatted)
            elif line.startswith("H2600HEADING"):
                match = TRAILING_FLOAT_RE.search(line)
                if match:
                    _set_if_empty(info, "line heading", match.group(1))
                    formatted = format_line_direction(match.group(1))
                    if formatted:
                        _set_if_empty(info, "line direction", formatted)
            elif "SHOT POINT INTERVAL" in line:
                match = TRAILING_FLOAT_RE.search(line)
                if match:
                    _set_if_empty(info, "shot point interval", match.group(1))
            elif "PREPLOT LINE NUMBER" in line.upper():
                value = _p190_value(line)
                if not value and ":" in line:
                    value = line.rsplit(":", 1)[-1].strip()
                _set_if_empty(info, "preplot line number", value)
            elif "NUMBER OF SAILLINES" in line:
                match = TRAILING_INT_RE.search(line)
                if match:
                    _set_if_empty(info, "number of saillines", match.group(1))
            elif ":" in line[1:]:
                text = line[1:].strip()
                text = H_NUM_PREFIX.sub("", text)
                key, _, value = text.partition(":")
                _set_if_empty(info, key, value)
    epsg = _extract_epsg(
        info.get("epsg code", ""),
        info.get("crs name", ""),
        info.get("projection", ""),
    )
    if epsg:
        _set_if_empty(info, "epsg code", epsg)
    else:
        central_meridian, false_easting, false_northing, scale_factor = _p190_grid_parameters(
            info
        )
        inferred = infer_epsg_from_header(
            info.get("geographic datum", ""),
            info.get("projection", ""),
            info.get("projection zone", ""),
            central_meridian=central_meridian,
            false_easting=false_easting,
            false_northing=false_northing,
            scale_factor=scale_factor,
        )
        if inferred:
            _set_if_empty(info, "epsg code", inferred)
            _set_if_empty(info, "crs name", f"EPSG:{inferred}")
    return info


def parse_file_metadata(path: Path, fmt: str | None = None) -> dict[str, str]:
    if fmt is None:
        suffix = path.suffix.lower()
        fmt = "p111" if suffix == ".p111" else "p190"
        if suffix not in (".p111", ".p190"):
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for _ in range(15):
                    line = handle.readline()
                    if not line:
                        break
                    if line.startswith("H,"):
                        fmt = "p111"
                        break
                    if line.startswith("H") and ":" in line:
                        fmt = "p190"
                        break
    if fmt == "p111":
        return parse_p111_metadata(path)
    return parse_p190_metadata(path)


def merge_metadata(*sources: dict[str, str]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for source in sources:
        for key, value in source.items():
            _set_if_empty(merged, key, value)
    return merged


def _lookup(info: dict[str, str], *keys: str) -> str:
    for key in keys:
        norm = _normalize_key(key)
        if norm in info and info[norm]:
            return info[norm]
    return ""


def metadata_to_postmap(
    info: dict[str, str],
    settings: ProjectSettings,
    existing: PostmapInfo | None = None,
    file_name: str = "",
) -> PostmapInfo:
    """Build PostmapInfo from parsed header metadata."""
    base = existing or PostmapInfo()
    crs = _lookup(info, "crs", "coordinate reference system", "name")
    projection = _lookup(info, "projection", "crs", "coordinate reference system")
    epsg = _lookup(info, "epsg code", "epsg", "authority", "epsg code")
    if not epsg:
        epsg = _extract_epsg(crs, projection)

    def pick(base_value: str, *meta_keys: str) -> str:
        from_meta = _lookup(info, *meta_keys)
        if (base_value or "").strip():
            return base_value.strip()
        return from_meta

    result = PostmapInfo(
        company_name=base.company_name,
        title=pick(base.title, "title", "survey title", "job title"),
        job_number=pick(base.job_number, "job number", "job no", "job_number"),
        client=pick(base.client, "client name", "client", "client_name"),
        area=pick(
            base.area,
            "area",
            "survey area",
            "survey area/description",
            "description",
            "survey description",
        ),
        project=pick(base.project, "project name", "project", "project_name") or settings.name,
        client_ref=pick(
            base.client_ref,
            "client project reference",
            "client ref",
            "client reference",
            "client_project_reference",
        ),
        file_name=pick(base.file_name, "file name", "file_name") or file_name,
        user_name=pick(base.user_name, "user name", "user", "operator"),
        date=pick(base.date, "date", "creation date", "survey date"),
        crs_name=pick(base.crs_name, "crs name", "coordinate reference system", "crs", "name") or crs,
        projection=pick(base.projection, "projection") or projection or crs,
        epsg_code=pick(base.epsg_code, "epsg code", "epsg", "authority") or epsg,
        geographic_datum=pick(
            base.geographic_datum,
            "geographic datum",
            "datum",
            "geodetic datum",
        ),
        spheroid=pick(base.spheroid, "spheroid", "reference spheroid"),
        semi_major_axis=pick(
            base.semi_major_axis,
            "semi-major axis",
            "semi major axis",
            "semi_major_axis",
        ),
        inverse_flattening=pick(
            base.inverse_flattening,
            "inverse flattening",
            "inv flattening",
        ),
        eccentricity=pick(base.eccentricity, "eccentricity"),
        extra={**base.extra, **info},
    )
    if result.epsg_code:
        result.epsg_code = normalize_epsg(result.epsg_code)
    return result


def collect_postmap_metadata(
    paths: list[Path],
    settings: ProjectSettings,
    existing: PostmapInfo | None = None,
) -> PostmapInfo:
    """Merge metadata from multiple files; later files fill empty fields only."""
    merged: dict[str, str] = {}
    primary_name = paths[0].name if paths else ""
    for path in paths:
        suffix = path.suffix.lower()
        fmt = "p111" if suffix == ".p111" else None
        merged = merge_metadata(merged, parse_file_metadata(path, fmt))
    return metadata_to_postmap(merged, settings, existing, file_name=primary_name)
