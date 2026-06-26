"""P111 (IOGP P1/11) CSV navigation file parser."""

from __future__ import annotations

import re
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from xpostmaps.core.models import PositionRecord, RecordType

# If the header LINE-DIRECTION disagrees with the actual source track by more
# than this, the header is treated as unreliable and the data-derived track is
# used for the feather. A correctly headed line tracks within ~1-2 deg; a gross
# mismatch (observed up to ~52 deg) yields physically impossible feathers.
LINE_DIRECTION_TRACK_TOLERANCE_DEG = 5.0
S1_REC_TIME_IDX = 7

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
R_REC_SPN_IDX = 4
R_REC_PREPLOT_IDX = 5
R_REC_STREAMER_ID_IDX = 9
R_REC_RECEIVER_NUM_IDX = 11
R_REC_EASTING_IDX = 12
R_REC_NORTHING_IDX = 13

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


@dataclass(frozen=True)
class ReceiverFeatherRecord:
    shotpoint: int
    line_name: str
    streamer_id: str
    feather_deg: float
    sequence_no: str = ""
    subline: str = ""
    preplot_no: str = ""


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


def _calculate_azimuth_degrees(x1: float, y1: float, x2: float, y2: float) -> float | None:
    dx = x2 - x1
    dy = y2 - y1
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return None
    return math.degrees(math.atan2(dx, dy)) % 360.0


def calculate_receiver_feather_deg(
    first_receiver: tuple[float, float],
    last_receiver: tuple[float, float],
    line_direction_deg: float,
) -> float | None:
    """Return signed streamer feather angle: starboard positive, port negative."""
    streamer_azimuth = _calculate_azimuth_degrees(
        first_receiver[0],
        first_receiver[1],
        last_receiver[0],
        last_receiver[1],
    )
    if streamer_azimuth is None:
        return None
    reciprocal_line = (line_direction_deg + 180.0) % 360.0
    return (reciprocal_line - streamer_azimuth + 180.0) % 360.0 - 180.0


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


def _receiver_positions_from_r1_fields(
    fields: list[str],
    axis_order: tuple[str, str] | None,
) -> list[tuple[int, float, float]]:
    receivers: list[tuple[int, float, float]] = []
    index = R_REC_RECEIVER_NUM_IDX
    while index + 2 < len(fields):
        receiver_text = _field(fields, index)
        if receiver_text.isdigit():
            receiver_num = _parse_int(receiver_text)
            x, y = _projected_xy_from_fields(
                fields,
                index + 1,
                index + 2,
                axis_order,
            )
            if receiver_num > 0 and x == x and y == y:
                receivers.append((receiver_num, x, y))
                index += 3
                continue
        index += 1
    return receivers


def _circular_mean_deg(angles: list[float]) -> float | None:
    if not angles:
        return None
    sin_sum = sum(math.sin(math.radians(a)) for a in angles)
    cos_sum = sum(math.cos(math.radians(a)) for a in angles)
    if abs(sin_sum) < 1e-12 and abs(cos_sum) < 1e-12:
        return None
    return math.degrees(math.atan2(sin_sum, cos_sum)) % 360.0


def scan_p111_source_track_deg(
    path: Path,
    axis_order: tuple[str, str] | None,
) -> float | None:
    """Derive the directed sail-line azimuth from S1 source positions.

    The header LINE-DIRECTION can be wrong; the over-ground track of a single
    source (sorted by time) is an authoritative, data-derived line direction.
    Using one source avoids the crossline jumps of an alternating flip-flop-flap
    source array. Returns ``None`` when no usable track is present.
    """
    by_source: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                if not raw_line.startswith("S1,"):
                    continue
                fields = raw_line.rstrip("\n\r").split(",")
                if len(fields) <= max(
                    S1_REC_SOURCE_FIRED_IDX, S1_REC_NORTHING_IDX, S1_REC_TIME_IDX
                ):
                    continue
                source_id = _field(fields, S1_REC_SOURCE_FIRED_IDX)
                try:
                    timestamp = float(_field(fields, S1_REC_TIME_IDX))
                except ValueError:
                    continue
                x, y = _projected_xy_from_fields(
                    fields, S1_REC_EASTING_IDX, S1_REC_NORTHING_IDX, axis_order
                )
                if x == x and y == y:
                    by_source[source_id].append((timestamp, x, y))
    except OSError:
        return None

    if not by_source:
        return None
    source_id = max(by_source, key=lambda key: len(by_source[key]))
    points = sorted(by_source[source_id])
    if len(points) < 2:
        return None
    azimuths: list[float] = []
    for (_, x0, y0), (_, x1, y1) in zip(points, points[1:]):
        dx, dy = x1 - x0, y1 - y0
        if dx * dx + dy * dy < 1.0:  # ignore sub-metre jitter between fixes
            continue
        azimuths.append(math.degrees(math.atan2(dx, dy)) % 360.0)
    return _circular_mean_deg(azimuths)


def _resolve_feather_line_direction(
    header_direction: float | None,
    track_direction: float | None,
) -> float | None:
    """Pick the line direction for feather, preferring a validated header."""
    if track_direction is None:
        return header_direction
    if header_direction is None:
        return track_direction
    delta = abs(((header_direction - track_direction + 180.0) % 360.0) - 180.0)
    if delta > LINE_DIRECTION_TRACK_TOLERANCE_DEG:
        return track_direction
    return header_direction


def parse_p111_receiver_feathers(path: Path) -> list[ReceiverFeatherRecord]:
    """Parse per-streamer receiver feather from P1/11 R1 records.

    A streamer's receivers for one shotpoint may be split across several R1
    rows (e.g. Shearwater files list ~800 receivers per row, 3200+ per
    streamer). All rows for a (shotpoint, streamer) are accumulated and the
    feather is computed from the GLOBAL first and last receiver (head to tail)
    using the active line direction from the CC headers. Files that pack a
    whole streamer in a single row (e.g. 10221, 240 receivers) behave
    identically.
    """
    records: list[ReceiverFeatherRecord] = []
    file_name = path.name
    axis_order = scan_projected_axis_order(path)
    track_direction = scan_p111_source_track_deg(path, axis_order)
    current_sequence = "N/A"
    current_line_name = "N/A"
    current_subline = ""
    current_line_direction: float | None = None
    has_cc_headers = False

    # Per shotpoint: streamer_id -> endpoint extents.
    # [min_num, (mx, my), max_num, (Mx, My), preplot_no]
    current_shotpoint = 0
    accumulator: dict[str, list] = {}

    def flush() -> None:
        if current_shotpoint <= 0:
            return
        effective_direction = _resolve_feather_line_direction(
            current_line_direction, track_direction
        )
        if effective_direction is None:
            return
        line_name = current_line_name if has_cc_headers else file_name
        for streamer_id, ext in accumulator.items():
            min_num, first_xy, max_num, last_xy, preplot_no = ext
            if max_num <= min_num:
                continue
            feather = calculate_receiver_feather_deg(
                first_xy,
                last_xy,
                effective_direction,
            )
            if feather is None:
                continue
            records.append(
                ReceiverFeatherRecord(
                    shotpoint=current_shotpoint,
                    line_name=line_name or "UNNAMED",
                    streamer_id=streamer_id,
                    feather_deg=feather,
                    sequence_no=current_sequence,
                    subline=current_subline,
                    preplot_no=preplot_no,
                )
            )

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

            if not line.startswith("R1,"):
                continue
            if current_line_direction is None and track_direction is None:
                continue

            fields = line.split(",")
            if len(fields) <= max(R_REC_SPN_IDX, R_REC_STREAMER_ID_IDX, R_REC_RECEIVER_NUM_IDX):
                continue

            shotpoint = _parse_int(_field(fields, R_REC_SPN_IDX))
            streamer_id = _field(fields, R_REC_STREAMER_ID_IDX)
            if shotpoint <= 0 or not streamer_id:
                continue

            if shotpoint != current_shotpoint:
                flush()
                accumulator = {}
                current_shotpoint = shotpoint

            receivers = _receiver_positions_from_r1_fields(fields, axis_order)
            if not receivers:
                continue
            row_first = min(receivers, key=lambda item: item[0])
            row_last = max(receivers, key=lambda item: item[0])
            preplot_no = _field(fields, R_REC_PREPLOT_IDX)

            ext = accumulator.get(streamer_id)
            if ext is None:
                accumulator[streamer_id] = [
                    row_first[0],
                    (row_first[1], row_first[2]),
                    row_last[0],
                    (row_last[1], row_last[2]),
                    preplot_no,
                ]
            else:
                if row_first[0] < ext[0]:
                    ext[0] = row_first[0]
                    ext[1] = (row_first[1], row_first[2])
                if row_last[0] > ext[2]:
                    ext[2] = row_last[0]
                    ext[3] = (row_last[1], row_last[2])

        flush()
    return records


_P190_R_GROUP_WIDTH = 26
_P190_R_STREAMER_COL = 79


def _parse_p190_r_groups(line: str) -> list[tuple[int, float, float]]:
    """Parse up to 3 receiver groups (group_no, easting, northing) from an R record."""
    groups: list[tuple[int, float, float]] = []
    pos = 1
    length = len(line)
    while pos + 22 <= length:
        block = line[pos : pos + _P190_R_GROUP_WIDTH]
        group_text = block[0:4].strip()
        easting_text = block[4:13].strip()
        northing_text = block[13:22].strip()
        if not group_text or not easting_text or not northing_text:
            break
        try:
            group_no = int(group_text)
            easting = float(easting_text)
            northing = float(northing_text)
        except ValueError:
            break
        groups.append((group_no, easting, northing))
        pos += _P190_R_GROUP_WIDTH
    return groups


def _p190_streamer_id(line: str) -> str:
    """Streamer/cable id from the trailing P190 R-record column (col 80)."""
    if len(line) > _P190_R_STREAMER_COL:
        token = line[_P190_R_STREAMER_COL].strip()
        if token:
            return token
    stripped = line.rstrip()
    return stripped[-1] if stripped else ""


def parse_p190_receiver_feathers(path: Path) -> list[ReceiverFeatherRecord]:
    """Parse per-streamer receiver feather from a P190 file.

    P190 receiver (``R``) records pack up to three receiver groups per line and
    carry the streamer/cable number in the final column. Receiver group numbers
    restart per streamer, so the first/last receiver of each streamer is found
    by min/max group number within that streamer for each shotpoint.
    """
    # Avoid a circular import at module load time.
    from xpostmaps.parsers.p190_parser import (
        _parse_linename_subline_from_filename,
        parse_p190_header,
    )

    info = parse_p190_header(path)
    # Prefer the full-precision numeric line direction; "line direction" is a
    # display string rounded to 2 dp, which biases the feather angle.
    direction_source = info.get("line direction value") or info.get(
        "line direction", ""
    )
    direction_match = re.search(r"[-+]?\d+(?:\.\d+)?", direction_source)
    if direction_match is None:
        return []
    line_direction = float(direction_match.group(0))
    sequence_no = info.get("line sequence number", "") or "N/A"
    fallback_line, fallback_subline = _parse_linename_subline_from_filename(path)
    header_line_name = info.get("line name", "") or fallback_line
    subline = info.get("subline", "") or fallback_subline

    records: list[ReceiverFeatherRecord] = []
    current_shotpoint = 0
    current_line_name = header_line_name
    accumulator: dict[str, list[tuple[int, float, float]]] = {}

    def flush() -> None:
        if current_shotpoint <= 0 or not accumulator:
            return
        for streamer_id, groups in accumulator.items():
            if len(groups) < 2:
                continue
            first = min(groups, key=lambda item: item[0])
            last = max(groups, key=lambda item: item[0])
            feather = calculate_receiver_feather_deg(
                (first[1], first[2]),
                (last[1], last[2]),
                line_direction,
            )
            if feather is None:
                continue
            records.append(
                ReceiverFeatherRecord(
                    shotpoint=current_shotpoint,
                    line_name=current_line_name or "UNNAMED",
                    streamer_id=streamer_id,
                    feather_deg=feather,
                    sequence_no=sequence_no,
                    subline=subline,
                    preplot_no="",
                )
            )

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n\r")
            if not line:
                continue
            record_id = line[0].upper()
            if record_id == "S":
                flush()
                accumulator = {}
                current_shotpoint = _parse_int(line[19:25])
                name = line[1:13].strip()
                current_line_name = name or header_line_name
            elif record_id == "R" and current_shotpoint > 0:
                streamer_id = _p190_streamer_id(line) or "1"
                groups = _parse_p190_r_groups(line)
                if groups:
                    accumulator.setdefault(streamer_id, []).extend(groups)
    flush()
    return records


def average_receiver_feathers_by_shotpoint(
    records: list[ReceiverFeatherRecord],
) -> dict[int, float]:
    grouped: dict[int, list[float]] = {}
    for record in records:
        grouped.setdefault(record.shotpoint, []).append(record.feather_deg)
    return {
        shotpoint: sum(values) / len(values)
        for shotpoint, values in grouped.items()
        if values
    }


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
