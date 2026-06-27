"""P111 (IOGP P1/11) CSV navigation file parser."""

from __future__ import annotations

import re
import math
import os
import ctypes
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from xpostmaps.core.models import PositionRecord, RecordType

_DRIVE_REMOTE = 4


def _is_remote_feather_path(path: Path) -> bool:
    """True when the file lives on a UNC/network (SMB) share.

    Feather parsing is network-I/O bound for large files: the multi-core path
    reads the file twice (chunk-plan pass + worker pass), which doubles the SMB
    transfer with no page-cache benefit. On a network share that is slower than
    a single streaming pass, so we keep the process pool for local disk only.
    """
    text = str(path)
    if text.startswith("\\\\"):
        return True
    if os.name != "nt":
        return False
    try:
        if not path.drive:
            return False
        return ctypes.windll.kernel32.GetDriveTypeW(path.drive + "\\") == _DRIVE_REMOTE
    except Exception:  # noqa: BLE001
        return False

# If the header LINE-DIRECTION disagrees with the actual source track by more
# than this, the header is treated as unreliable and the data-derived track is
# used for the feather. A correctly headed line tracks within ~1-2 deg; a gross
# mismatch (observed up to ~52 deg) yields physically impossible feathers.
LINE_DIRECTION_TRACK_TOLERANCE_DEG = 5.0
S1_REC_TIME_IDX = 7
_FEATHER_PROCESS_MIN_BYTES = 128 * 1024 * 1024
_MAX_FEATHER_PARSE_WORKERS = 8
_P111_FEATHER_SHOTS_PER_CHUNK = 24

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


ReceiverEndpointTargets = dict[str, tuple[int, int]]


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


def _streamer_aliases(identifier: str) -> set[str]:
    text = (identifier or "").strip()
    if not text:
        return set()
    aliases = {text, text.upper()}
    match = re.search(r"(\d+)$", text)
    if match:
        num = int(match.group(1))
        aliases.update({str(num), f"S{num}", f"S{num:02d}"})
    return {alias for alias in aliases if alias}


def _raw_aliases(identifier: str) -> set[str]:
    text = (identifier or "").strip()
    if not text:
        return set()
    return {text, text.upper()}


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


def scan_echosounder_id(path: Path, scan_limit: int = 2000) -> str | None:
    """Scan P111 header for echosounder/transducer device ID (xp111.py logic)."""
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
                if (
                    "echo sounder" in device_type
                    or "echosounder" in device_type
                    or description == "Transducer Position"
                ):
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


def scan_p111_header_context(
    path: Path,
    scan_limit: int = 5000,
) -> tuple[str | None, str | None, frozenset[str], tuple[str, str] | None]:
    """Scan P111 header once for vessel, echosounder, gun codes, and axis order."""
    vessel_id: str | None = None
    echosounder_id: str | None = None
    gun_codes: set[str] = set()
    axes_by_crs: dict[str, dict[int, str]] = {}
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for i, line in enumerate(handle):
                if i >= scan_limit:
                    break
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith(("P1,", "S1,", "R1,")):
                    break
                if stripped.startswith("HC,2,"):
                    fields = stripped.split(",")
                    if len(fields) > 8:
                        device_id = _field(fields, 6)
                        device_type = _field(fields, 8).lower()
                        description = _field(fields, 15) if len(fields) > 15 else ""
                        if device_id:
                            if vessel_id is None and (
                                device_type == "vessel"
                                or description == "Vessel Reference Point"
                            ):
                                vessel_id = device_id
                            if echosounder_id is None and (
                                "echo sounder" in device_type
                                or "echosounder" in device_type
                                or description == "Transducer Position"
                            ):
                                echosounder_id = device_id
                            if (
                                stripped.startswith("HC,2,3,0,")
                                and (device_type == "air gun array" or _fallback_gun_code(device_id))
                            ):
                                gun_codes.add(device_id)
                    continue
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
        return None, None, frozenset(), None

    axis_order: tuple[str, str] | None = None
    for axes in axes_by_crs.values():
        ordered = tuple(axes[index] for index in sorted(axes))
        if set(ordered) == {"easting", "northing"} and len(ordered) >= 2:
            axis_order = ordered[:2]
            break
    return vessel_id, echosounder_id, frozenset(gun_codes), axis_order


def scan_p111_receiver_endpoint_targets(
    path: Path,
    scan_limit: int = 20_000,
) -> ReceiverEndpointTargets:
    """Return streamer -> (first receiver, last receiver) from P1/11 headers."""
    object_aliases: dict[str, set[str]] = {}
    targets: ReceiverEndpointTargets = {}
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for i, line in enumerate(handle):
                if i >= scan_limit:
                    break
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith(("P1,", "S1,", "R1,")):
                    break
                if stripped.startswith("HC,2,3,0,"):
                    fields = stripped.split(",")
                    if len(fields) > 8 and _field(fields, 8).lower() == "streamer":
                        object_id = _field(fields, 5)
                        streamer_code = _field(fields, 6)
                        label = _field(fields, 4)
                        aliases = set()
                        aliases.update(_raw_aliases(object_id))
                        aliases.update(_streamer_aliases(streamer_code))
                        aliases.update(_streamer_aliases(label))
                        if object_id and aliases:
                            object_aliases[object_id] = aliases
                    continue
                if "Receiver Group Definition" not in stripped:
                    continue
                fields = stripped.split(",")
                if len(fields) <= 11:
                    continue
                object_id = _field(fields, 6)
                first_receiver = _parse_int(_field(fields, 7))
                last_candidates = [
                    _parse_int(_field(fields, idx))
                    for idx in (11, 15)
                    if idx < len(fields)
                ]
                last_receiver = max([value for value in last_candidates if value > 0], default=0)
                if first_receiver <= 0 or last_receiver <= first_receiver:
                    continue
                aliases = object_aliases.get(object_id, set(_raw_aliases(object_id)))
                for alias in aliases:
                    targets[alias] = (first_receiver, last_receiver)
    except OSError:
        return {}
    return targets


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


def _receiver_endpoint_positions_from_r1_fields(
    fields: list[str],
    axis_order: tuple[str, str] | None,
    endpoint_targets: set[int] | None,
) -> list[tuple[int, float, float]]:
    if not endpoint_targets:
        return _receiver_positions_from_r1_fields(fields, axis_order)
    receivers: list[tuple[int, float, float]] = []
    remaining = set(endpoint_targets)
    index = R_REC_RECEIVER_NUM_IDX
    while index + 2 < len(fields) and remaining:
        receiver_text = _field(fields, index)
        if receiver_text.isdigit():
            receiver_num = _parse_int(receiver_text)
            if receiver_num in remaining:
                x, y = _projected_xy_from_fields(
                    fields,
                    index + 1,
                    index + 2,
                    axis_order,
                )
                if receiver_num > 0 and x == x and y == y:
                    receivers.append((receiver_num, x, y))
                    remaining.discard(receiver_num)
            index += 3
            continue
        index += 1
    return receivers


def _p111_source_track_from_points(
    by_source: dict[str, list[tuple[float, float, float]]],
) -> float | None:
    if not by_source:
        return None
    source_id = max(by_source, key=lambda key: len(by_source[key]))
    points = sorted(by_source[source_id])
    if len(points) < 2:
        return None
    azimuths: list[float] = []
    for (_, x0, y0), (_, x1, y1) in zip(points, points[1:]):
        dx, dy = x1 - x0, y1 - y0
        if dx * dx + dy * dy < 1.0:
            continue
        azimuths.append(math.degrees(math.atan2(dx, dy)) % 360.0)
    return _circular_mean_deg(azimuths)


def _parse_p111_shotpoint_from_r1_bytes(raw: bytes) -> int:
    try:
        parts = raw.split(b",", R_REC_SPN_IDX + 2)
        if len(parts) <= R_REC_SPN_IDX:
            return 0
        return int(float(parts[R_REC_SPN_IDX].strip() or b"0"))
    except (ValueError, TypeError):
        return 0


def _p111_worker_count(chunk_count: int) -> int:
    if chunk_count <= 1:
        return 1
    cpu_count = os.cpu_count() or 2
    return max(1, min(chunk_count, max(1, cpu_count - 1), _MAX_FEATHER_PARSE_WORKERS))


def _p111_feather_chunk_plan(
    path: Path,
    axis_order: tuple[str, str] | None,
    *,
    shots_per_chunk: int = _P111_FEATHER_SHOTS_PER_CHUNK,
) -> tuple[list[tuple[int, int, str, str, str, float | None, bool]], float | None]:
    chunks: list[tuple[int, int, str, str, str, float | None, bool]] = []
    source_points: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
    current_sequence = "N/A"
    current_line_name = "N/A"
    current_subline = ""
    current_line_direction: float | None = None
    has_cc_headers = False
    chunk_start: int | None = None
    chunk_context = (current_sequence, current_line_name, current_subline, current_line_direction, has_cc_headers)
    chunk_shots: set[int] = set()
    last_shotpoint = 0
    try:
        with path.open("rb") as handle:
            while True:
                line_start = handle.tell()
                raw = handle.readline()
                if not raw:
                    break
                if raw.startswith(b"CC,1,0,0,LINE SEQUENCE NUMBER ="):
                    has_cc_headers = True
                    try:
                        current_sequence = raw.decode("utf-8", "replace").split("=", 1)[1].strip() or "N/A"
                    except IndexError:
                        pass
                    continue
                if raw.startswith(b"CC,1,0,0,LINENAME/SUBLINE ="):
                    has_cc_headers = True
                    try:
                        parts = raw.decode("utf-8", "replace").split("=", 1)[1].strip()
                        name_parts = [p for p in parts.split("/") if p]
                        current_line_name = name_parts[0] if name_parts else "N/A"
                        current_subline = name_parts[1] if len(name_parts) > 1 else ""
                    except (IndexError, ValueError):
                        pass
                    continue
                if raw.startswith(b"CC,1,0,0,LINE-DIRECTION ="):
                    has_cc_headers = True
                    try:
                        current_line_direction = float(raw.decode("utf-8", "replace").split("=", 1)[1].strip())
                    except (IndexError, ValueError, TypeError):
                        current_line_direction = None
                    continue
                if raw.startswith(b"S1,"):
                    try:
                        fields = raw.decode("utf-8", "replace").rstrip("\n\r").split(",")
                        if len(fields) > max(S1_REC_SOURCE_FIRED_IDX, S1_REC_NORTHING_IDX, S1_REC_TIME_IDX):
                            source_id = _field(fields, S1_REC_SOURCE_FIRED_IDX)
                            timestamp = float(_field(fields, S1_REC_TIME_IDX))
                            x, y = _projected_xy_from_fields(
                                fields,
                                S1_REC_EASTING_IDX,
                                S1_REC_NORTHING_IDX,
                                axis_order,
                            )
                            if x == x and y == y:
                                source_points[source_id].append((timestamp, x, y))
                    except (ValueError, IndexError):
                        pass
                    continue
                if not raw.startswith(b"R1,"):
                    continue
                shotpoint = _parse_p111_shotpoint_from_r1_bytes(raw)
                if shotpoint <= 0:
                    continue
                if chunk_start is None:
                    chunk_start = line_start
                    chunk_context = (
                        current_sequence,
                        current_line_name,
                        current_subline,
                        current_line_direction,
                        has_cc_headers,
                    )
                if shotpoint != last_shotpoint:
                    if len(chunk_shots) >= shots_per_chunk and chunk_start < line_start:
                        chunks.append(
                            (
                                chunk_start,
                                line_start,
                                chunk_context[0],
                                chunk_context[1],
                                chunk_context[2],
                                chunk_context[3],
                                chunk_context[4],
                            )
                        )
                        chunk_start = line_start
                        chunk_context = (
                            current_sequence,
                            current_line_name,
                            current_subline,
                            current_line_direction,
                            has_cc_headers,
                        )
                        chunk_shots = set()
                    chunk_shots.add(shotpoint)
                    last_shotpoint = shotpoint
            file_end = handle.tell()
        if chunk_start is not None and chunk_start < file_end:
            chunks.append(
                (
                    chunk_start,
                    file_end,
                    chunk_context[0],
                    chunk_context[1],
                    chunk_context[2],
                    chunk_context[3],
                    chunk_context[4],
                )
            )
    except OSError:
        return [], None
    return chunks, _p111_source_track_from_points(source_points)


def _p111_feather_chunk_worker(
    args: tuple[
        str,
        int,
        int,
        str,
        str,
        str,
        float | None,
        bool,
        tuple[str, str] | None,
        dict[str, tuple[int, int]],
        float | None,
    ],
) -> list[ReceiverFeatherRecord]:
    (
        raw_path,
        start,
        end,
        current_sequence,
        current_line_name,
        current_subline,
        current_line_direction,
        has_cc_headers,
        axis_order,
        receiver_targets,
        track_direction,
    ) = args
    records: list[ReceiverFeatherRecord] = []
    current_shotpoint = 0
    accumulator: dict[str, list] = {}

    def flush() -> None:
        nonlocal accumulator, current_shotpoint
        if current_shotpoint <= 0:
            return
        effective_direction = _resolve_feather_line_direction(
            current_line_direction,
            track_direction,
        )
        if effective_direction is None:
            accumulator = {}
            return
        line_name = current_line_name if has_cc_headers else Path(raw_path).name
        for streamer_id, ext in accumulator.items():
            min_num, first_xy, max_num, last_xy, preplot_no = ext
            target = receiver_targets.get(streamer_id)
            if max_num <= min_num:
                continue
            if target and (min_num != target[0] or max_num != target[1]):
                continue
            feather = calculate_receiver_feather_deg(first_xy, last_xy, effective_direction)
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
        accumulator = {}

    try:
        with Path(raw_path).open("rb") as handle:
            handle.seek(start)
            for raw in handle:
                if handle.tell() > end:
                    break
                if not raw.startswith(b"R1,"):
                    continue
                line = raw.decode("utf-8", "replace").strip()
                fields = line.split(",")
                if len(fields) <= max(R_REC_SPN_IDX, R_REC_STREAMER_ID_IDX, R_REC_RECEIVER_NUM_IDX):
                    continue
                shotpoint = _parse_int(_field(fields, R_REC_SPN_IDX))
                streamer_id = _field(fields, R_REC_STREAMER_ID_IDX)
                if shotpoint <= 0 or not streamer_id:
                    continue
                if shotpoint != current_shotpoint:
                    flush()
                    current_shotpoint = shotpoint
                target = receiver_targets.get(streamer_id)
                ext = accumulator.get(streamer_id)
                if target and ext is not None and ext[0] == target[0] and ext[2] == target[1]:
                    continue
                receivers = _receiver_endpoint_positions_from_r1_fields(
                    fields,
                    axis_order,
                    set(target) if target else None,
                )
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
    except OSError:
        return []
    return records


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


def _track_bearing_from_source_positions(
    by_source: dict[str, list[tuple[int, float, float]]],
) -> float | None:
    """Mean over-ground bearing of the most-sampled source, sorted by shotpoint.

    The result is an accurate *line bearing* but its sign is only as reliable as
    the shotpoint numbering: P190 shotpoints may increase opposite to the actual
    direction of travel, so callers must orient the bearing (see
    :func:`_orient_track_to_streamers`) before using it as a directed heading.
    """
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


def scan_p190_source_track_deg(path: Path) -> float | None:
    """Return the shotpoint-ordered source-track bearing for a P190 file.

    Unlike the P111 track (ordered by acquisition time), P190 is ordered by
    shotpoint, so the returned bearing is direction-ambiguous (it may be the
    reciprocal of the true heading). Use :func:`_orient_track_to_streamers` to
    resolve the sign from streamer geometry before validating a header.
    """
    by_source: dict[str, list[tuple[int, float, float]]] = defaultdict(list)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                line = raw_line.rstrip("\n\r")
                if len(line) < 64 or line[0].upper() != "S":
                    continue
                try:
                    shotpoint = int(line[19:25])
                    # UKOOA P1/90 fixed columns: easting 47-55, northing 56-64.
                    x = float(line[46:55])
                    y = float(line[55:64])
                except ValueError:
                    continue
                by_source[line[17:18].strip()].append((shotpoint, x, y))
    except OSError:
        return None
    return _track_bearing_from_source_positions(by_source)


def _orient_track_to_streamers(
    track_bearing: float | None,
    mean_streamer_azimuth: float | None,
) -> float | None:
    """Resolve the 180-degree ambiguity of a P190 track bearing using streamers.

    Streamers trail *behind* the vessel, so the true heading opposes the mean
    streamer head->tail azimuth. When the shotpoint-ordered bearing points along
    the streamers (i.e. with the tail, not into the heading), flip it by 180 deg
    so it becomes a correctly-directed sail heading.
    """
    if track_bearing is None:
        return None
    if mean_streamer_azimuth is None:
        return track_bearing
    expected_heading = (mean_streamer_azimuth + 180.0) % 360.0
    delta = abs(((track_bearing - expected_heading + 180.0) % 360.0) - 180.0)
    if delta > 90.0:
        return (track_bearing + 180.0) % 360.0
    return track_bearing


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
    receiver_targets = scan_p111_receiver_endpoint_targets(path)
    track_direction: float | None = None
    try:
        file_size = path.stat().st_size
    except OSError:
        file_size = 0
    # Multi-core only pays off on local disk: it reads the file twice (plan +
    # worker passes) and relies on the OS page cache to make the second read
    # free. On a network share that second read is a full SMB re-transfer, so a
    # single streaming pass is faster there.
    if (
        file_size >= _FEATHER_PROCESS_MIN_BYTES
        and receiver_targets
        and not _is_remote_feather_path(path)
    ):
        chunks, planned_track = _p111_feather_chunk_plan(path, axis_order)
        track_direction = planned_track
        worker_count = _p111_worker_count(len(chunks))
        if chunks and worker_count > 1:
            worker_args = [
                (
                    str(path),
                    start,
                    end,
                    sequence,
                    line_name,
                    subline,
                    line_direction,
                    has_headers,
                    axis_order,
                    receiver_targets,
                    track_direction,
                )
                for start, end, sequence, line_name, subline, line_direction, has_headers
                in chunks
            ]
            try:
                with ProcessPoolExecutor(max_workers=worker_count) as executor:
                    for chunk_records in executor.map(_p111_feather_chunk_worker, worker_args):
                        records.extend(chunk_records)
                if records:
                    return sorted(
                        records,
                        key=lambda record: (
                            record.sequence_no,
                            record.line_name,
                            record.subline,
                            record.shotpoint,
                            record.streamer_id,
                        ),
                    )
            except Exception:  # noqa: BLE001
                records = []
    if track_direction is None:
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
            target = receiver_targets.get(streamer_id)
            if max_num <= min_num:
                continue
            if target and (min_num != target[0] or max_num != target[1]):
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

            target = receiver_targets.get(streamer_id)
            ext = accumulator.get(streamer_id)
            if target and ext is not None and ext[0] == target[0] and ext[2] == target[1]:
                continue
            receivers = _receiver_endpoint_positions_from_r1_fields(
                fields,
                axis_order,
                set(target) if target else None,
            )
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


def scan_p190_receiver_endpoint_targets(path: Path, scan_limit: int = 50_000) -> ReceiverEndpointTargets:
    """Return streamer/cable id -> (first group, last group) from P1/90 headers."""
    targets: ReceiverEndpointTargets = {}
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for i, raw_line in enumerate(handle):
                if i >= scan_limit:
                    break
                line = raw_line.rstrip("\n\r")
                if not line:
                    continue
                if line[0].upper() in {"S", "R", "V", "E"}:
                    break
                upper = line.upper()
                if "STREAMER DETAILS" not in upper or "RECEIVERS" not in upper:
                    continue
                tokens = line.replace(":", " ").split()
                streamer = ""
                streamer_index = -1
                count = 0
                for index, token in enumerate(tokens):
                    if re.fullmatch(r"S\d+", token.upper()) and index + 1 < len(tokens):
                        streamer = token.upper()
                        streamer_index = index
                        count = _parse_int(tokens[index + 1])
                        break
                if not streamer or count <= 1:
                    continue
                trailing = [
                    token
                    for token in tokens[streamer_index + 2 :]
                    if token.upper() != "RECEIVERS"
                ]
                aliases = set(_streamer_aliases(streamer))
                if trailing:
                    aliases.update(_raw_aliases(trailing[-1]))
                for alias in aliases:
                    targets[alias] = (1, count)
    except OSError:
        return {}
    return targets


def _parse_p190_r_groups(
    line: str,
    endpoint_targets: set[int] | None = None,
) -> list[tuple[int, float, float]]:
    """Parse receiver groups, optionally only endpoint group numbers."""
    groups: list[tuple[int, float, float]] = []
    pos = 1
    length = len(line)
    remaining = set(endpoint_targets or ())
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
        if endpoint_targets is None or group_no in remaining:
            groups.append((group_no, easting, northing))
            remaining.discard(group_no)
            if endpoint_targets is not None and not remaining:
                break
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


def _p190_feather_chunk_plan(
    path: Path,
    *,
    shots_per_chunk: int = _P111_FEATHER_SHOTS_PER_CHUNK,
) -> list[tuple[int, int]]:
    chunks: list[tuple[int, int]] = []
    chunk_start: int | None = None
    shot_count = 0
    try:
        with path.open("rb") as handle:
            while True:
                line_start = handle.tell()
                raw = handle.readline()
                if not raw:
                    break
                if not raw:
                    continue
                if raw[:1].upper() != b"S":
                    continue
                if chunk_start is None:
                    chunk_start = line_start
                    shot_count = 1
                    continue
                if shot_count >= shots_per_chunk and chunk_start < line_start:
                    chunks.append((chunk_start, line_start))
                    chunk_start = line_start
                    shot_count = 1
                else:
                    shot_count += 1
            file_end = handle.tell()
        if chunk_start is not None and chunk_start < file_end:
            chunks.append((chunk_start, file_end))
    except OSError:
        return []
    return chunks


def _p190_feather_chunk_worker(
    args: tuple[
        str,
        int,
        int,
        str,
        dict[str, tuple[int, int]],
    ],
) -> tuple[
    list[tuple[int, str, str, tuple[float, float], tuple[float, float]]],
    list[float],
    dict[str, list[tuple[int, float, float]]],
]:
    raw_path, start, end, header_line_name, receiver_targets = args
    pending: list[tuple[int, str, str, tuple[float, float], tuple[float, float]]] = []
    streamer_azimuths: list[float] = []
    source_positions: dict[str, list[tuple[int, float, float]]] = defaultdict(list)
    current_shotpoint = 0
    current_line_name = header_line_name
    accumulator: dict[str, list] = {}

    def commit_shot() -> None:
        nonlocal accumulator
        if current_shotpoint <= 0 or not accumulator:
            accumulator = {}
            return
        for streamer_id, ext in accumulator.items():
            min_g, first_xy, max_g, last_xy = ext
            target = receiver_targets.get(streamer_id)
            if max_g <= min_g:
                continue
            if target and (min_g != target[0] or max_g != target[1]):
                continue
            pending.append(
                (
                    current_shotpoint,
                    current_line_name or "UNNAMED",
                    streamer_id,
                    first_xy,
                    last_xy,
                )
            )
            azimuth = _calculate_azimuth_degrees(
                first_xy[0],
                first_xy[1],
                last_xy[0],
                last_xy[1],
            )
            if azimuth is not None:
                streamer_azimuths.append(azimuth)
        accumulator = {}

    try:
        with Path(raw_path).open("rb") as handle:
            handle.seek(start)
            for raw in handle:
                if handle.tell() > end:
                    break
                line = raw.decode("utf-8", "replace").rstrip("\n\r")
                if not line:
                    continue
                record_id = line[0].upper()
                if record_id == "S":
                    commit_shot()
                    current_shotpoint = _parse_int(line[19:25])
                    name = line[1:13].strip()
                    current_line_name = name or header_line_name
                    if len(line) >= 64:
                        try:
                            sx = float(line[46:55])
                            sy = float(line[55:64])
                        except ValueError:
                            pass
                        else:
                            source_positions[line[17:18].strip()].append(
                                (current_shotpoint, sx, sy)
                            )
                elif record_id == "R" and current_shotpoint > 0:
                    streamer_id = _p190_streamer_id(line) or "1"
                    target = receiver_targets.get(streamer_id)
                    ext = accumulator.get(streamer_id)
                    if target and ext is not None and ext[0] == target[0] and ext[2] == target[1]:
                        continue
                    groups = _parse_p190_r_groups(line, set(target) if target else None)
                    if not groups:
                        continue
                    row_first = min(groups, key=lambda item: item[0])
                    row_last = max(groups, key=lambda item: item[0])
                    ext = accumulator.get(streamer_id)
                    if ext is None:
                        accumulator[streamer_id] = [
                            row_first[0],
                            (row_first[1], row_first[2]),
                            row_last[0],
                            (row_last[1], row_last[2]),
                        ]
                    else:
                        if row_first[0] < ext[0]:
                            ext[0] = row_first[0]
                            ext[1] = (row_first[1], row_first[2])
                        if row_last[0] > ext[2]:
                            ext[2] = row_last[0]
                            ext[3] = (row_last[1], row_last[2])
            commit_shot()
    except OSError:
        return [], [], {}
    return pending, streamer_azimuths, source_positions


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
    header_direction = float(direction_match.group(0)) if direction_match else None
    sequence_no = info.get("line sequence number", "") or "N/A"
    fallback_line, fallback_subline = _parse_linename_subline_from_filename(path)
    header_line_name = info.get("line name", "") or fallback_line
    subline = info.get("subline", "") or fallback_subline
    receiver_targets = scan_p190_receiver_endpoint_targets(path)

    try:
        file_size = path.stat().st_size
    except OSError:
        file_size = 0
    # See parse_p111_receiver_feathers: multi-core re-reads the file, so keep it
    # for local disk and use a single streaming pass on network shares.
    if (
        file_size >= _FEATHER_PROCESS_MIN_BYTES
        and receiver_targets
        and not _is_remote_feather_path(path)
    ):
        chunks = _p190_feather_chunk_plan(path)
        worker_count = _p111_worker_count(len(chunks))
        if chunks and worker_count > 1:
            pending: list[tuple[int, str, str, tuple[float, float], tuple[float, float]]] = []
            streamer_azimuths: list[float] = []
            source_positions: dict[str, list[tuple[int, float, float]]] = defaultdict(list)
            worker_args = [
                (str(path), start, end, header_line_name, receiver_targets)
                for start, end in chunks
            ]
            try:
                with ProcessPoolExecutor(max_workers=worker_count) as executor:
                    for chunk_pending, chunk_azimuths, chunk_sources in executor.map(
                        _p190_feather_chunk_worker,
                        worker_args,
                    ):
                        pending.extend(chunk_pending)
                        streamer_azimuths.extend(chunk_azimuths)
                        for source_id, points in chunk_sources.items():
                            source_positions[source_id].extend(points)
                track_bearing = _track_bearing_from_source_positions(source_positions)
                mean_streamer_azimuth = _circular_mean_deg(streamer_azimuths)
                oriented_track = _orient_track_to_streamers(
                    track_bearing,
                    mean_streamer_azimuth,
                )
                line_direction = _resolve_feather_line_direction(
                    header_direction,
                    oriented_track,
                )
                if line_direction is not None and pending:
                    records: list[ReceiverFeatherRecord] = []
                    for shotpoint, line_name, streamer_id, first_xy, last_xy in pending:
                        feather = calculate_receiver_feather_deg(
                            first_xy,
                            last_xy,
                            line_direction,
                        )
                        if feather is None:
                            continue
                        records.append(
                            ReceiverFeatherRecord(
                                shotpoint=shotpoint,
                                line_name=line_name,
                                streamer_id=streamer_id,
                                feather_deg=feather,
                                sequence_no=sequence_no,
                                subline=subline,
                                preplot_no="",
                            )
                        )
                    if records:
                        return sorted(
                            records,
                            key=lambda record: (
                                record.sequence_no,
                                record.line_name,
                                record.subline,
                                record.shotpoint,
                                record.streamer_id,
                            ),
                        )
            except Exception:  # noqa: BLE001
                pass

    # Single pass: collect each (shotpoint, streamer) head/tail endpoint, the
    # source track positions, and the streamer azimuths. The feather needs the
    # validated line direction, which itself needs the streamer geometry to
    # orient the direction-ambiguous P190 track, so feather computation is
    # deferred until the whole file has been read.
    pending: list[tuple[int, str, str, tuple[float, float], tuple[float, float]]] = []
    streamer_azimuths: list[float] = []
    source_positions: dict[str, list[tuple[int, float, float]]] = defaultdict(list)

    current_shotpoint = 0
    current_line_name = header_line_name
    # streamer_id -> [min_group, first_xy, max_group, last_xy]
    accumulator: dict[str, list] = {}

    def commit_shot() -> None:
        if current_shotpoint <= 0 or not accumulator:
            return
        for streamer_id, ext in accumulator.items():
            min_g, first_xy, max_g, last_xy = ext
            target = receiver_targets.get(streamer_id)
            if max_g <= min_g:
                continue
            if target and (min_g != target[0] or max_g != target[1]):
                continue
            pending.append(
                (
                    current_shotpoint,
                    current_line_name or "UNNAMED",
                    streamer_id,
                    first_xy,
                    last_xy,
                )
            )
            azimuth = _calculate_azimuth_degrees(
                first_xy[0], first_xy[1], last_xy[0], last_xy[1]
            )
            if azimuth is not None:
                streamer_azimuths.append(azimuth)

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n\r")
            if not line:
                continue
            record_id = line[0].upper()
            if record_id == "S":
                commit_shot()
                accumulator = {}
                current_shotpoint = _parse_int(line[19:25])
                name = line[1:13].strip()
                current_line_name = name or header_line_name
                if len(line) >= 64:
                    try:
                        sx = float(line[46:55])
                        sy = float(line[55:64])
                    except ValueError:
                        pass
                    else:
                        source_positions[line[17:18].strip()].append(
                            (current_shotpoint, sx, sy)
                        )
            elif record_id == "R" and current_shotpoint > 0:
                streamer_id = _p190_streamer_id(line) or "1"
                target = receiver_targets.get(streamer_id)
                ext = accumulator.get(streamer_id)
                if target and ext is not None and ext[0] == target[0] and ext[2] == target[1]:
                    continue
                groups = _parse_p190_r_groups(line, set(target) if target else None)
                if not groups:
                    continue
                row_first = min(groups, key=lambda item: item[0])
                row_last = max(groups, key=lambda item: item[0])
                ext = accumulator.get(streamer_id)
                if ext is None:
                    accumulator[streamer_id] = [
                        row_first[0],
                        (row_first[1], row_first[2]),
                        row_last[0],
                        (row_last[1], row_last[2]),
                    ]
                else:
                    if row_first[0] < ext[0]:
                        ext[0] = row_first[0]
                        ext[1] = (row_first[1], row_first[2])
                    if row_last[0] > ext[2]:
                        ext[2] = row_last[0]
                        ext[3] = (row_last[1], row_last[2])
        commit_shot()

    # Validate the header against the data-derived heading (as for P111): a
    # grossly wrong header (>5 deg off) yields physically impossible feathers,
    # and a missing header would otherwise drop the feather entirely. The P190
    # track bearing is direction-ambiguous, so orient it with the streamer
    # trailing geometry before comparing.
    track_bearing = _track_bearing_from_source_positions(source_positions)
    mean_streamer_azimuth = _circular_mean_deg(streamer_azimuths)
    oriented_track = _orient_track_to_streamers(track_bearing, mean_streamer_azimuth)
    line_direction = _resolve_feather_line_direction(header_direction, oriented_track)
    if line_direction is None:
        return []

    records: list[ReceiverFeatherRecord] = []
    for shotpoint, line_name, streamer_id, first_xy, last_xy in pending:
        feather = calculate_receiver_feather_deg(first_xy, last_xy, line_direction)
        if feather is None:
            continue
        records.append(
            ReceiverFeatherRecord(
                shotpoint=shotpoint,
                line_name=line_name,
                streamer_id=streamer_id,
                feather_deg=feather,
                sequence_no=sequence_no,
                subline=subline,
                preplot_no="",
            )
        )
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

    scanned_vessel_id, echosounder_id, gun_codes, axis_order = scan_p111_header_context(path)
    if vessel_id is None:
        vessel_id = scanned_vessel_id

    current_sequence = "N/A"
    current_line_name = "N/A"
    current_subline = ""
    current_line_direction: float | None = None
    has_cc_headers = False
    pending_firing: _PendingFiringShot | None = None
    depth_by_shot: dict[tuple[str, int], float] = {}
    record_indices_by_shot: dict[tuple[str, int], list[int]] = {}

    def _shot_key(point_num: int) -> tuple[str, int]:
        return current_sequence, point_num

    def _parse_p1_depth(fields: list[str]) -> float | None:
        if not fields:
            return None
        raw = fields[-1].strip().split(";", 1)[0].strip()
        if not raw:
            return None
        try:
            depth = float(raw)
        except ValueError:
            return None
        return depth

    def _remember_record_depth(record: PositionRecord) -> None:
        key = (record.sequence_no, record.point_num)
        record_indices_by_shot.setdefault(key, []).append(len(records) - 1)
        if key in depth_by_shot:
            record.depth = depth_by_shot[key]

    def _apply_depth(point_num: int, depth: float) -> None:
        key = _shot_key(point_num)
        depth_by_shot[key] = depth
        for record_index in record_indices_by_shot.get(key, []):
            records[record_index].depth = depth

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
                depth=depth_by_shot.get(_shot_key(pending_firing.point_num)),
                latitude=pending_firing.latitude,
                longitude=pending_firing.longitude,
                sequence_no=current_sequence,
                line_direction=_format_line_direction(current_line_direction),
                subline=current_subline,
            )
        )
        _remember_record_depth(records[-1])
        pending_firing = None

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            if raw_line.startswith("R1,"):
                # Receiver rows are handled only by the Diff Stat feather parser.
                # Skip them here before strip/split: streamer P111 files can be GBs.
                continue
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

                if echosounder_id and device_id == echosounder_id and point_num > 0:
                    depth = _parse_p1_depth(fields)
                    if depth is not None:
                        _apply_depth(point_num, depth)
                    continue

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
                        depth=depth_by_shot.get(_shot_key(point_num)),
                        latitude=_field(fields, P_REC_LATITUDE_IDX),
                        longitude=_field(fields, P_REC_LONGITUDE_IDX),
                        sequence_no=current_sequence,
                        line_direction=_format_line_direction(current_line_direction),
                        subline=current_subline,
                    )
                )
                _remember_record_depth(records[-1])
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
