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


def crs_match(source: str | int | None, target: str | int | None) -> bool:
    src = normalize_epsg(source)
    dst = normalize_epsg(target)
    return bool(src and dst and src == dst)


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
