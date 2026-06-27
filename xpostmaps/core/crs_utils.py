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


def geographic_epsg_from_map(map_epsg: str | int | None) -> str:
    """Return the geographic EPSG paired with the map/projected CRS.

    Diff Stat lat/long uses this so geographic coordinates stay on the same
    datum as easting/northing (e.g. EPSG:2193 → EPSG:4167, EPSG:23031 → EPSG:4230).
    """
    code = normalize_epsg(map_epsg)
    if not code:
        return WGS84_EPSG
    try:
        from pyproj import CRS

        crs = CRS.from_epsg(int(code))
        if crs.is_geographic:
            return code
        geodetic = crs.geodetic_crs
        if geodetic is not None:
            authority = geodetic.to_authority()
            if authority:
                return normalize_epsg(str(authority[1]))
    except Exception:  # noqa: BLE001
        pass
    return WGS84_EPSG


def _approx_equal(left: float, right: float, tolerance: float = 1e-3) -> bool:
    return abs(left - right) <= tolerance


# Geographic (datum) EPSG codes used as the base CRS when reconstructing a
# projected CRS from raw grid parameters via pyproj.
_GEOGRAPHIC_CRS_BY_DATUM = {
    "WGS 84": "EPSG:4326",
    "ED50": "EPSG:4230",
    "ETRS89": "EPSG:4258",
    "NAD83": "EPSG:4269",
    "NAD27": "EPSG:4267",
    "NZGD2000": "EPSG:4167",
    "GDA94": "EPSG:4283",
    "GDA2020": "EPSG:7844",
    "OSGB36": "EPSG:4277",
}

# Fallback geographic bases tried (in order) when the detected datum does not
# yield a match. Kept small and ordered by global frequency to limit the risk
# of a false positive.
_GEOGRAPHIC_CRS_FALLBACKS = (
    "EPSG:4167",  # NZGD2000 (NZTM headers often mislabel datum as WGS-84)
    "EPSG:4326",  # WGS 84
    "EPSG:4258",  # ETRS89
    "EPSG:4283",  # GDA94
    "EPSG:7844",  # GDA2020
    "EPSG:4230",  # ED50
)


def detect_datum_name(datum: str) -> str:
    """Return a canonical datum label from free-form P190/P111 datum text."""
    datum_text = (datum or "").upper()
    if "ED50" in datum_text or "ED-50" in datum_text:
        return "ED50"
    if "GDA2020" in datum_text or "GDA 2020" in datum_text:
        return "GDA2020"
    if "GDA94" in datum_text or "GDA 94" in datum_text:
        return "GDA94"
    if "NZGD2000" in datum_text or "NZTM2000" in datum_text or "NZGD 2000" in datum_text:
        return "NZGD2000"
    if "ETRS89" in datum_text or "ETRS 89" in datum_text:
        return "ETRS89"
    if "NAD83" in datum_text or "NAD 83" in datum_text:
        return "NAD83"
    if "NAD27" in datum_text or "NAD 27" in datum_text:
        return "NAD27"
    if "OSGB" in datum_text or "OSGB36" in datum_text:
        return "OSGB36"
    if re.search(r"WGS[\s\-]?84", datum_text):
        return "WGS 84"
    return ""


def epsg_from_grid_parameters(
    datum_name: str,
    central_meridian: float | None,
    false_easting: float | None,
    false_northing: float | None,
    scale_factor: float | None,
    latitude_of_origin: float = 0.0,
) -> str:
    """Resolve an EPSG code for a Transverse Mercator grid via pyproj.

    Reconstructs the projected CRS from raw grid parameters and asks PROJ for
    the matching authority code. Tries the detected datum first, then a small
    set of common geographic bases. Returns "" when pyproj is unavailable or no
    confident match is found.
    """
    if (
        central_meridian is None
        or false_easting is None
        or false_northing is None
        or scale_factor is None
    ):
        return ""
    try:
        from pyproj import CRS
        from pyproj.crs import ProjectedCRS
        from pyproj.crs.coordinate_operation import TransverseMercatorConversion
    except Exception:  # noqa: BLE001
        return ""

    candidates: list[str] = []
    base = _GEOGRAPHIC_CRS_BY_DATUM.get(datum_name)
    if base:
        candidates.append(base)
    for code in _GEOGRAPHIC_CRS_FALLBACKS:
        if code not in candidates:
            candidates.append(code)

    try:
        conversion = TransverseMercatorConversion(
            latitude_natural_origin=latitude_of_origin,
            longitude_natural_origin=central_meridian,
            false_easting=false_easting,
            false_northing=false_northing,
            scale_factor_natural_origin=scale_factor,
        )
    except Exception:  # noqa: BLE001
        return ""

    for geo in candidates:
        try:
            geographic_crs = CRS.from_user_input(geo)
            projected = ProjectedCRS(
                conversion=conversion,
                geodetic_crs=geographic_crs,
            )
            epsg = projected.to_epsg(min_confidence=70)
        except Exception:  # noqa: BLE001
            continue
        if epsg is not None:
            return str(epsg)
    return ""


def infer_epsg_from_header(
    datum: str = "",
    projection: str = "",
    zone: str = "",
    *,
    central_meridian: float | None = None,
    false_easting: float | None = None,
    false_northing: float | None = None,
    scale_factor: float | None = None,
) -> str:
    """Infer an EPSG code from P190/P111 datum + projection + zone headers.

    Header text is not always a complete CRS definition, so explicit EPSG values
    remain authoritative. This helper only covers unambiguous common cases and
    asks pyproj/PROJ to resolve the final authority code.
    """
    projection_text = (projection or "").upper()
    zone_text = (zone or "").upper().strip()

    datum_name = detect_datum_name(datum)

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

    is_transverse_mercator = (
        "TRANSVERSE MERCATOR" in projection_text
        or projection_text.strip() in {"TM", "003"}
        or projection_text.endswith(" TM")
    )
    if is_transverse_mercator:
        # NZTM grid fingerprint: stable even when pyproj is unavailable or the
        # header mislabels the datum as WGS-84 instead of NZGD2000.
        if (
            central_meridian is not None
            and false_easting is not None
            and false_northing is not None
            and scale_factor is not None
            and _approx_equal(central_meridian, 173.0)
            and _approx_equal(false_easting, 1_600_000.0)
            and _approx_equal(false_northing, 10_000_000.0)
            and _approx_equal(scale_factor, 0.9996, tolerance=1e-5)
        ):
            return (
                from_user_input("NZGD2000 / New Zealand Transverse Mercator 2000")
                or "2193"
            )
        if "NEW ZEALAND" in projection_text or datum_name == "NZGD2000":
            return (
                from_user_input("NZGD2000 / New Zealand Transverse Mercator 2000")
                or "2193"
            )
        # General case: reconstruct the TM grid from raw parameters and let
        # PROJ resolve the authority code (covers arbitrary TM zones/datums).
        grid_epsg = epsg_from_grid_parameters(
            datum_name,
            central_meridian,
            false_easting,
            false_northing,
            scale_factor,
        )
        if grid_epsg:
            return grid_epsg

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
