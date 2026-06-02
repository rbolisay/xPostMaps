"""Extract postmap metadata from P111/P190/Navplan file headers."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from xpostmaps.core.crs_utils import normalize_epsg
from xpostmaps.core.models import PostmapInfo, ProjectSettings

EPSG_RE = re.compile(r"EPSG\s*[:\s]?\s*(\d+)", re.IGNORECASE)
H_NUM_PREFIX = re.compile(r"^\d+\s+")
TRAILING_INT_RE = re.compile(r"(\d+)\s*$")
TRAILING_FLOAT_RE = re.compile(r"([\d.]+)\s*$")


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
    elif label.startswith("CRS Number/EPSG Code") and len(row) >= 10:
        crs_name = row[9].strip() if len(row) > 9 else ""
        epsg = row[6].strip()
        if "UTM" in crs_name or "utm" in crs_name.lower():
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
                if text.startswith("HEADING"):
                    match = TRAILING_FLOAT_RE.search(text)
                    if match:
                        _set_if_empty(info, "line heading", match.group(1))
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
    return info


def _p190_value(line: str) -> str:
    return line[32:].strip() if len(line) > 32 else line.strip()


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
                if parts:
                    _set_if_empty(info, "geographic datum", parts[0])
                    if len(parts) >= 2:
                        _set_if_empty(info, "crs name", " ".join(parts[1:3]))
            elif line.startswith("H1800"):
                _set_if_empty(info, "projection", _p190_value(line))
            elif "CRS EPSG Code" in line:
                match = TRAILING_INT_RE.search(line)
                if match:
                    _set_if_empty(info, "epsg code", match.group(1))
            elif line.startswith("H2600HEADING"):
                match = TRAILING_FLOAT_RE.search(line)
                if match:
                    _set_if_empty(info, "line heading", match.group(1))
            elif "SHOT POINT INTERVAL" in line:
                match = TRAILING_FLOAT_RE.search(line)
                if match:
                    _set_if_empty(info, "shot point interval", match.group(1))
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
        return from_meta or base_value

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
