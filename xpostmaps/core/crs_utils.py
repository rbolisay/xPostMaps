"""Coordinate reference system helpers for polygon import."""

from __future__ import annotations

import re
from pathlib import Path

WGS84_EPSG = "4326"

EPSG_DIGITS_RE = re.compile(r"(\d{3,6})")


def normalize_epsg(code: str | int | None) -> str:
    """Return bare EPSG authority code digits, or empty string."""
    if code is None:
        return ""
    text = str(code).strip()
    if not text:
        return ""
    upper = text.upper()
    if upper.startswith("EPSG:"):
        text = text[5:].strip()
    elif upper.startswith("EPSG"):
        text = text[4:].lstrip(": ").strip()
    match = EPSG_DIGITS_RE.search(text)
    return match.group(1) if match else ""


def epsg_label(code: str | int | None) -> str:
    normalized = normalize_epsg(code)
    return f"EPSG:{normalized}" if normalized else "unknown CRS"


def infer_epsg_from_header(
    datum: str = "",
    projection: str = "",
    zone: str = "",
) -> str:
    """Infer an EPSG code from P190/P111 datum + projection + zone headers.

    Header text is not always a complete CRS definition, so explicit EPSG values
    remain authoritative. This helper only covers unambiguous common cases and
    asks pyproj/PROJ to resolve the final authority code.
    """
    datum_text = (datum or "").upper()
    projection_text = (projection or "").upper()
    zone_text = (zone or "").upper().strip()

    datum_name = ""
    if "ED50" in datum_text or "ED-50" in datum_text:
        datum_name = "ED50"
    elif "WGS84" in datum_text or "WGS 84" in datum_text:
        datum_name = "WGS 84"
    elif "ETRS89" in datum_text or "ETRS 89" in datum_text:
        datum_name = "ETRS89"
    elif "NAD83" in datum_text or "NAD 83" in datum_text:
        datum_name = "NAD83"
    elif "NAD27" in datum_text or "NAD 27" in datum_text:
        datum_name = "NAD27"
    elif "NZGD2000" in datum_text or "NZTM2000" in datum_text:
        datum_name = "NZGD2000"

    try:
        from pyproj import CRS
    except Exception:  # noqa: BLE001
        CRS = None

    def from_user_input(text: str) -> str:
        if CRS is None:
            return ""
        try:
            epsg = CRS.from_user_input(text).to_epsg()
        except Exception:  # noqa: BLE001
            return ""
        return str(epsg) if epsg is not None else ""

    def known_utm_epsg(zone_num: int, hemisphere: str) -> str:
        if not 1 <= zone_num <= 60:
            return ""
        if datum_name == "WGS 84":
            return str(32600 + zone_num if hemisphere == "N" else 32700 + zone_num)
        if hemisphere != "N":
            return ""
        if datum_name == "ED50" and 28 <= zone_num <= 38:
            return str(23000 + zone_num)
        if datum_name == "ETRS89" and 28 <= zone_num <= 38:
            return str(25800 + zone_num)
        if datum_name == "NAD83" and 1 <= zone_num <= 23:
            return str(26900 + zone_num)
        if datum_name == "NAD27" and 3 <= zone_num <= 22:
            return str(26700 + zone_num)
        return ""

    if "UTM" in projection_text or "U.T.M" in projection_text:
        match = re.search(r"(\d{1,2})\s*([NS])?", zone_text)
        if match is None:
            match = re.search(r"ZONE\s*(\d{1,2})\s*([NS])?", projection_text)
        if match:
            zone_num = int(match.group(1))
            hemisphere = match.group(2) or (
                "S" if "SOUTH" in projection_text else "N"
            )
            fallback_epsg = known_utm_epsg(zone_num, hemisphere)
            if datum_name:
                return (
                    from_user_input(f"{datum_name} / UTM zone {zone_num}{hemisphere}")
                    or fallback_epsg
                )
            return fallback_epsg

    if (
        "TRANSVERSE MERCATOR" in projection_text
        and ("NEW ZEALAND" in projection_text or datum_name == "NZGD2000")
    ):
        return from_user_input("NZGD2000 / New Zealand Transverse Mercator 2000") or "2193"

    return ""


def crs_match(source: str | int | None, target: str | int | None) -> bool:
    src = normalize_epsg(source)
    dst = normalize_epsg(target)
    return bool(src and dst and src == dst)


def pyproj_available() -> bool:
    """Return True when pyproj/PROJ is importable for coordinate transforms."""
    try:
        import pyproj  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def epsg_from_prj_path(prj_path: Path) -> str:
    """Read EPSG code from a shapefile .prj sidecar."""
    if not prj_path.is_file():
        return ""
    try:
        wkt = prj_path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    if not wkt:
        return ""
    try:
        from pyproj import CRS

        crs = CRS.from_wkt(wkt)
        epsg = crs.to_epsg()
        if epsg is not None:
            return str(epsg)
        auth = crs.to_authority()
        if auth and auth[0].upper() == "EPSG":
            return normalize_epsg(auth[1])
    except Exception:
        pass
    upper = wkt.upper()
    if "WGS_1984" in upper or "WGS 84" in upper:
        if "UTM" in upper:
            zone_match = re.search(r"UTM[_\s]*ZONE[_\s]*(\d{1,2})([NS])?", upper)
            if zone_match:
                zone = int(zone_match.group(1))
                hem = zone_match.group(2) or "N"
                return str(32600 + zone if hem == "N" else 32700 + zone)
        return WGS84_EPSG
    return ""


def transform_coordinates(
    xs: list[float],
    ys: list[float],
    source_epsg: str | int,
    target_epsg: str | int,
) -> tuple[list[float], list[float]]:
    """Reproject coordinate pairs from source EPSG to target EPSG."""
    src = normalize_epsg(source_epsg)
    dst = normalize_epsg(target_epsg)
    if not src or not dst or src == dst:
        return list(xs), list(ys)
    if not xs or len(xs) != len(ys):
        return [], []

    from pyproj import Transformer

    transformer = Transformer.from_crs(
        f"EPSG:{src}",
        f"EPSG:{dst}",
        always_xy=True,
    )
    out_x: list[float] = []
    out_y: list[float] = []
    for x, y in zip(xs, ys):
        if x != x or y != y:
            continue
        tx, ty = transformer.transform(x, y)
        out_x.append(float(tx))
        out_y.append(float(ty))
    return out_x, out_y
