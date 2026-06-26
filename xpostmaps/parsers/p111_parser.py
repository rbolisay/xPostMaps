"""P111 (IOGP P1/11) CSV navigation file parser."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from xpostmaps.core.models import PositionRecord, RecordType

# CC header card prefixes (from xp111.py)
CC_SEQUENCE_PREFIX = "CC,1,0,0,LINE SEQUENCE NUMBER ="
CC_LINENAME_PREFIX = "CC,1,0,0,LINENAME/SUBLINE ="
CC_LINE_DIRECTION_PREFIX = "CC,1,0,0,LINE-DIRECTION ="

# P1 record field indices (0-based after split)
P_REC_SPN_IDX = 4
P_REC_PREPLOT_IDX = 5
P_REC_DEVICE_ID_IDX = 9
P_REC_EASTING_IDX = 12
P_REC_NORTHING_IDX = 13
P_REC_LATITUDE_IDX = 15
P_REC_LONGITUDE_IDX = 16

# S1 record field indices
S1_REC_SPN_IDX = 4
S1_REC_PREPLOT_IDX = 5
S1_REC_SOURCE_FIRED_IDX = 9
S1_REC_EASTING_IDX = 12
S1_REC_NORTHING_IDX = 13
S1_REC_LATITUDE_IDX = 15
S1_REC_LONGITUDE_IDX = 16

# Legacy V1/S1 short-form indices (fallback when CC context is absent)
LEGACY_LINE_IDX = 1
LEGACY_POINT_IDX = 3
LEGACY_X_IDX = 11
LEGACY_Y_IDX = 12
LEGACY_LAT_IDX = 14
LEGACY_LON_IDX = 15

P111_VESSEL_LEGACY_IDS = frozenset({"V1", "V2"})


@dataclass
class _PendingFiringShot:
    point_num: int
    firing_code: str
    x: float
    y: float
    latitude: str
    longitude: str
    line_name: str


def _parse_float(value: str) -> float:
    try:
        return float(value.replace(",", "").strip())
    except ValueError:
        return float("nan")


def _parse_int(value: str) -> int:
    try:
        return int(float(value.strip()))
    except ValueError:
        return 0


def _field(parts: list[str], index: int) -> str:
    if index < 0 or index >= len(parts):
        return ""
    return parts[index].strip()


def _format_line_direction(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.1f}°"


def _fallback_gun_code(code: str) -> bool:
    return code.startswith("G") and len(code) == 3 and code[1:].isdigit()


def scan_gun_array_codes(path: Path, scan_limit: int = 5000) -> frozenset[str]:
    """Return air-gun array codes (G01, G02, ...) from HC header definitions."""
    codes: set[str] = set()
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for i, line in enumerate(handle):
                if i >= scan_limit:
                    break
                line = line.strip()
                if not line:
                    continue
                if line.startswith(("S1,", "P1,", "R1,")):
                    break
                if not line.startswith("HC,2,3,0,"):
                    continue
                fields = line.split(",")
                if len(fields) <= 8:
                    continue
                code = _field(fields, 6)
                object_type = _field(fields, 8).lower()
                if not code:
                    continue
                if object_type == "air gun array" or _fallback_gun_code(code):
                    codes.add(code)
    except OSError:
        return frozenset()
    return frozenset(codes)


def scan_vessel_id(path: Path, scan_limit: int = 2000) -> str | None:
    """Scan P111 header for vessel device ID (matches xp111.py logic)."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for i, line in enumerate(handle):
                if i >= scan_limit:
                    break
                line = line.strip()
                if not line:
                    continue
                if line.startswith(("P1,", "S1,", "R1,")):
                    break
                if not line.startswith("HC,2,"):
                    continue
                fields = line.split(",")
                if len(fields) <= 8:
                    continue
                device_id = _field(fields, 6)
                if not device_id:
                    continue
                device_type = _field(fields, 8).lower()
                description = _field(fields, 15) if len(fields) > 15 else ""
                is_vessel = device_type == "vessel" or description == "Vessel Reference Point"
                if is_vessel:
                    return device_id
    except OSError:
        return None
    return None


def scan_projected_axis_order(path: Path, scan_limit: int = 2000) -> tuple[str, str] | None:
    """Return projected coordinate axis order, e.g. ("northing", "easting")."""
    axes_by_crs: dict[str, dict[int, str]] = {}
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for i, line in enumerate(handle):
                if i >= scan_limit:
                    break
                stripped = line.strip()
                if stripped.startswith(("S1,", "P1,", "R1,")):
                    break
                if not stripped.startswith("HC,1,6,1,"):
                    continue
                fields = [field.strip() for field in stripped.split(",")]
                if len(fields) < 9:
                    continue
                label = _field(fields, 4).lower()
                if "coordinate system axis" not in label:
                    continue
                crs_number = _field(fields, 5)
                try:
                    axis_number = int(_field(fields, 6))
                except ValueError:
                    continue
                axis_name = _field(fields, 8).lower()
                if "easting" in axis_name:
                    axis = "easting"
                elif "northing" in axis_name:
                    axis = "northing"
                else:
                    continue
                axes_by_crs.setdefault(crs_number, {})[axis_number] = axis
    except OSError:
        return None

    for axes in axes_by_crs.values():
        ordered = tuple(axes[index] for index in sorted(axes))
        if set(ordered) == {"easting", "northing"} and len(ordered) >= 2:
            return ordered[:2]
    return None


def _projected_xy_from_fields(
    fields: list[str],
    first_coord_index: int,
    second_coord_index: int,
    axis_order: tuple[str, str] | None,
) -> tuple[float, float]:
    first = _parse_float(_field(fields, first_coord_index))
    second = _parse_float(_field(fields, second_coord_index))
    if axis_order == ("northing", "easting"):
        return second, first
    return first, second


def _parse_legacy_line(
    line: str,
    file_name: str,
    record_type: RecordType,
) -> PositionRecord | None:
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 14:
        return None
    x = _parse_float(_field(parts, LEGACY_X_IDX))
    y = _parse_float(_field(parts, LEGACY_Y_IDX))
    if not (x == x and y == y):
        return None
    depth_val = _parse_float(_field(parts, 25)) if len(parts) > 25 else float("nan")
    return PositionRecord(
        file_name=file_name,
        record_type=record_type,
        line_name=_field(parts, LEGACY_LINE_IDX),
        vessel_id=_field(parts, 5),
        source_id=_field(parts, 8),
        point_num=_parse_int(_field(parts, LEGACY_POINT_IDX)),
        x=x,
        y=y,
        depth=depth_val if depth_val == depth_val else None,
        latitude=_field(parts, LEGACY_LAT_IDX),
        longitude=_field(parts, LEGACY_LON_IDX),
    )


def parse_p111_file(path: Path, vessel_id: str | None = None) -> list[PositionRecord]:
    """Parse vessel (P1) and firing-source positions (S1 + matching P1 only).

    Matches xSeisView shot-block logic: S1 identifies which gun fired at each
    shotpoint; coordinates prefer the matching P1 air-gun record. Other P1 gun
    positions (G01/G02/G03 arrays) are never emitted as source records.
    """
    records: list[PositionRecord] = []
    file_name = path.name

    if vessel_id is None:
        vessel_id = scan_vessel_id(path)
    gun_codes = scan_gun_array_codes(path)
    axis_order = scan_projected_axis_order(path)

    current_sequence = "N/A"
    current_line_name = "N/A"
    current_subline = ""
    current_line_direction: float | None = None
    has_cc_headers = False
    pending_firing: _PendingFiringShot | None = None

    def flush_firing() -> None:
        nonlocal pending_firing
        if pending_firing is None:
            return
        records.append(
            PositionRecord(
                file_name=file_name,
                record_type=RecordType.SOURCE,
                line_name=pending_firing.line_name or "UNNAMED",
                vessel_id="",
                source_id=pending_firing.firing_code,
                point_num=pending_firing.point_num,
                x=pending_firing.x,
                y=pending_firing.y,
                latitude=pending_firing.latitude,
                longitude=pending_firing.longitude,
                sequence_no=current_sequence,
                line_direction=_format_line_direction(current_line_direction),
                subline=current_subline,
            )
        )
        pending_firing = None

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            if line.startswith(CC_SEQUENCE_PREFIX):
                has_cc_headers = True
                try:
                    current_sequence = line.split("=", 1)[1].strip() or "N/A"
                except IndexError:
                    pass
                continue

            if line.startswith(CC_LINENAME_PREFIX):
                has_cc_headers = True
                try:
                    parts = line.split("=", 1)[1].strip()
                    name_parts = [p for p in parts.split("/") if p]
                    current_line_name = name_parts[0] if name_parts else "N/A"
                    current_subline = name_parts[1] if len(name_parts) > 1 else ""
                except (IndexError, ValueError):
                    pass
                continue

            if line.startswith(CC_LINE_DIRECTION_PREFIX):
                has_cc_headers = True
                try:
                    current_line_direction = float(line.split("=", 1)[1].strip())
                except (IndexError, ValueError, TypeError):
                    current_line_direction = None
                continue

            if line.startswith("S1,"):
                fields = line.split(",")
                min_fields = max(
                    S1_REC_SPN_IDX,
                    S1_REC_SOURCE_FIRED_IDX,
                    S1_REC_EASTING_IDX,
                    S1_REC_NORTHING_IDX,
                    S1_REC_LATITUDE_IDX,
                    S1_REC_LONGITUDE_IDX,
                ) + 1
                if len(fields) < min_fields:
                    continue

                firing_code = _field(fields, S1_REC_SOURCE_FIRED_IDX)
                point_num = _parse_int(_field(fields, S1_REC_SPN_IDX))
                if not firing_code or point_num <= 0:
                    continue

                x, y = _projected_xy_from_fields(
                    fields,
                    S1_REC_EASTING_IDX,
                    S1_REC_NORTHING_IDX,
                    axis_order,
                )
                if not (x == x and y == y):
                    continue

                flush_firing()
                line_name = current_line_name if has_cc_headers else _field(fields, LEGACY_LINE_IDX)
                pending_firing = _PendingFiringShot(
                    point_num=point_num,
                    firing_code=firing_code,
                    x=x,
                    y=y,
                    latitude=_field(fields, S1_REC_LATITUDE_IDX),
                    longitude=_field(fields, S1_REC_LONGITUDE_IDX),
                    line_name=line_name or "UNNAMED",
                )
                continue

            if line.startswith("P1,"):
                fields = line.split(",")
                if len(fields) <= max(P_REC_SPN_IDX, P_REC_DEVICE_ID_IDX, P_REC_NORTHING_IDX):
                    continue

                device_id = _field(fields, P_REC_DEVICE_ID_IDX)
                point_num = _parse_int(_field(fields, P_REC_SPN_IDX))

                if (
                    pending_firing is not None
                    and point_num == pending_firing.point_num
                    and device_id == pending_firing.firing_code
                ):
                    x, y = _projected_xy_from_fields(
                        fields,
                        P_REC_EASTING_IDX,
                        P_REC_NORTHING_IDX,
                        axis_order,
                    )
                    if x == x and y == y:
                        pending_firing.x = x
                        pending_firing.y = y
                        pending_firing.latitude = _field(fields, P_REC_LATITUDE_IDX)
                        pending_firing.longitude = _field(fields, P_REC_LONGITUDE_IDX)
                    continue

                if device_id in gun_codes or _fallback_gun_code(device_id):
                    continue

                if not vessel_id or device_id != vessel_id:
                    continue

                x, y = _projected_xy_from_fields(
                    fields,
                    P_REC_EASTING_IDX,
                    P_REC_NORTHING_IDX,
                    axis_order,
                )
                if not (x == x and y == y):
                    continue
                records.append(
                    PositionRecord(
                        file_name=file_name,
                        record_type=RecordType.VESSEL,
                        line_name=current_line_name or "UNNAMED",
                        vessel_id=device_id,
                        source_id="",
                        point_num=point_num,
                        x=x,
                        y=y,
                        depth=None,
                        latitude=_field(fields, P_REC_LATITUDE_IDX),
                        longitude=_field(fields, P_REC_LONGITUDE_IDX),
                        sequence_no=current_sequence,
                        line_direction=_format_line_direction(current_line_direction),
                        subline=current_subline,
                    )
                )
                continue

            record_id = line.split(",", 1)[0].upper()
            if record_id in P111_VESSEL_LEGACY_IDS:
                legacy = _parse_legacy_line(line, file_name, RecordType.VESSEL)
                if legacy is not None:
                    if has_cc_headers:
                        legacy.sequence_no = current_sequence
                        legacy.line_direction = _format_line_direction(current_line_direction)
                        legacy.subline = current_subline
                        if current_line_name != "N/A":
                            legacy.line_name = current_line_name
                    records.append(legacy)

    flush_firing()
    return records


def parse_p111_header(path: Path) -> dict[str, str]:
    info: dict[str, str] = {}
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped.startswith("H"):
                if re.match(r"^[SVEFRP]", stripped):
                    break
                continue
            text = stripped[1:].lstrip(",").strip()
            if "," in text:
                parts = [p.strip() for p in text.split(",")]
                if len(parts) >= 2:
                    info[parts[0].lower()] = parts[1]
            elif ":" in text:
                key, _, value = text.partition(":")
                info[key.strip().lower()] = value.strip()
    return info
