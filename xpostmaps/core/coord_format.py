"""Geographic coordinate parsing and DD MM.MM (N/S/E/W) formatting."""

from __future__ import annotations

import re

from xpostmaps.core.crs_utils import WGS84_EPSG, transform_coordinates

_DECIMAL_RE = re.compile(r"^[-+]?\d+(?:\.\d+)?$")


def _parse_dms_body(body: str, *, is_latitude: bool) -> tuple[int, int, float] | None:
    max_deg = 90 if is_latitude else 180
    layouts = [(2, 2)] if is_latitude else [(3, 2), (2, 2)]
    valid: list[tuple[int, int, int, float]] = []
    for deg_width, min_width in layouts:
        sec_start = deg_width + min_width
        if len(body) < sec_start + 1:
            continue
        deg = int(body[:deg_width])
        minute = int(body[deg_width:sec_start])
        second = float(body[sec_start:])
        if 0 <= deg <= max_deg and 0 <= minute < 60 and 0 <= second < 60:
            valid.append((deg_width, deg, minute, second))
    if not valid:
        return None
    if len(valid) == 1:
        _, deg, minute, second = valid[0]
        return deg, minute, second
    three = next((item for item in valid if item[0] == 3), None)
    two = next((item for item in valid if item[0] == 2), None)
    if three and two and three[1] >= 10 and two[1] < 10:
        return two[1], two[2], two[3]
    if three:
        return three[1], three[2], three[3]
    return two[1], two[2], two[3] if two else valid[0][1:3]


def dms_compact_to_decimal(text: str) -> float | None:
    """Parse ``593603.13N`` or ``0011012.37E`` style values to decimal degrees."""
    cleaned = (text or "").strip().upper().replace(" ", "")
    if len(cleaned) < 5:
        return None
    hem = cleaned[-1]
    if hem not in "NSEW":
        return None
    body = cleaned[:-1]
    parsed = _parse_dms_body(body, is_latitude=hem in "NS")
    if parsed is None:
        return None
    deg, minute, second = parsed
    value = deg + minute / 60.0 + second / 3600.0
    if hem in {"S", "W"}:
        value = -value
    return value


def parse_geo_value(text: str, *, is_latitude: bool) -> float | None:
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    if _DECIMAL_RE.match(cleaned.replace(",", "")):
        try:
            value = float(cleaned.replace(",", ""))
        except ValueError:
            return None
        limit = 90.0 if is_latitude else 180.0
        if abs(value) <= limit:
            return value
        return None
    return dms_compact_to_decimal(cleaned)


def format_dd_mm(value: float, *, is_latitude: bool) -> str:
    limit = 90.0 if is_latitude else 180.0
    clamped = max(-limit, min(limit, value))
    hem = "N" if clamped >= 0 else "S"
    if not is_latitude:
        hem = "E" if clamped >= 0 else "W"
    abs_val = abs(clamped)
    degrees = int(abs_val)
    minutes = (abs_val - degrees) * 60.0
    return f"{degrees} {minutes:.2f} {hem}"


def format_geo_display(
    raw: str,
    projected: float,
    *,
    is_latitude: bool,
    map_epsg: str = "",
    other_projected: float | None = None,
    formatter: "GeoDisplayFormatter | None" = None,
) -> str:
    """Format a coordinate for display as DD MM.MM (N/S/E/W)."""
    if formatter is not None:
        return formatter.format(
            raw,
            projected,
            is_latitude=is_latitude,
            other_projected=other_projected,
        )
    parsed = parse_geo_value(raw, is_latitude=is_latitude)
    if parsed is not None:
        return format_dd_mm(parsed, is_latitude=is_latitude)

    if map_epsg and projected == projected:
        if other_projected is None or other_projected != other_projected:
            return ""
        xs = [projected if not is_latitude else other_projected]
        ys = [other_projected if not is_latitude else projected]
        lons, lats = transform_coordinates(xs, ys, map_epsg, WGS84_EPSG)
        if not lats or not lons:
            return ""
        value = lats[0] if is_latitude else lons[0]
        return format_dd_mm(value, is_latitude=is_latitude)
    return ""


class GeoDisplayFormatter:
    """Batch-friendly lat/long formatter with a reused CRS transformer."""

    def __init__(self, map_epsg: str = "") -> None:
        from xpostmaps.core.crs_utils import normalize_epsg

        self._map_epsg = normalize_epsg(map_epsg)
        self._transformer = None
        if self._map_epsg and self._map_epsg != WGS84_EPSG:
            try:
                from pyproj import Transformer

                self._transformer = Transformer.from_crs(
                    f"EPSG:{self._map_epsg}",
                    f"EPSG:{WGS84_EPSG}",
                    always_xy=True,
                )
            except Exception:  # noqa: BLE001
                self._transformer = None

    def format(
        self,
        raw: str,
        projected: float,
        *,
        is_latitude: bool,
        other_projected: float | None = None,
    ) -> str:
        parsed = parse_geo_value(raw, is_latitude=is_latitude)
        if parsed is not None:
            return format_dd_mm(parsed, is_latitude=is_latitude)
        if self._transformer is None or projected != projected:
            return ""
        if other_projected is None or other_projected != other_projected:
            return ""
        easting = projected if not is_latitude else other_projected
        northing = other_projected if not is_latitude else projected
        try:
            lon, lat = self._transformer.transform(easting, northing)
        except Exception:  # noqa: BLE001
            return ""
        value = lat if is_latitude else lon
        return format_dd_mm(float(value), is_latitude=is_latitude)
