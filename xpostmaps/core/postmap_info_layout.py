"""Project information field layout shared by dialog and right pane."""

from __future__ import annotations

import json
import uuid
from typing import Any

from xpostmaps.core.crs_utils import epsg_label, normalize_epsg
from xpostmaps.core.models import PostmapInfo

LAYOUT_KEY = "__layout__"
CUSTOM_KEY = "__custom__"

LOCKED_HEADER_KEYS = ("client", "area", "project")

BUILTIN_LABELS: dict[str, str] = {
    "job_number": "Job Number",
    "client_ref": "Client Project Reference",
    "file_name": "File Name",
    "user_name": "User Name",
    "date": "Date",
    "crs_heading": "Coordinate Reference System",
    "crs_name": "Name",
    "projection": "Projection",
    "epsg_code": "EPSG Code",
    "geographic_datum": "Geographic Datum",
    "spheroid": "Spheroid",
}

READONLY_KEYS = frozenset({"crs_heading"})

DEFAULT_LAYOUT: list[dict[str, Any]] = [
    {"key": "job_number", "column": 0, "row": 0},
    {"key": "client_ref", "column": 0, "row": 1},
    {"key": "file_name", "column": 0, "row": 2},
    {"key": "user_name", "column": 0, "row": 3},
    {"key": "date", "column": 0, "row": 4},
    {"key": "crs_heading", "column": 1, "row": 0},
    {"key": "crs_name", "column": 1, "row": 1},
    {"key": "projection", "column": 1, "row": 2},
    {"key": "epsg_code", "column": 1, "row": 3},
    {"key": "geographic_datum", "column": 1, "row": 4},
    {"key": "spheroid", "column": 1, "row": 5},
]


def _parse_layout(raw: str) -> list[dict[str, Any]]:
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    items: list[dict[str, Any]] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key", "")).strip()
        if not key:
            continue
        try:
            column = int(entry.get("column", 0))
            row = int(entry.get("row", 0))
        except (TypeError, ValueError):
            continue
        items.append({"key": key, "column": max(0, min(1, column)), "row": max(0, row)})
    return items


def get_layout(info: PostmapInfo) -> list[dict[str, Any]]:
    stored = _parse_layout(info.extra.get(LAYOUT_KEY, ""))
    if stored:
        return sorted(stored, key=lambda e: (e["column"], e["row"]))
    return list(DEFAULT_LAYOUT)


def get_custom_fields(info: PostmapInfo) -> dict[str, dict[str, str]]:
    raw = info.extra.get(CUSTOM_KEY, "")
    if not raw.strip():
        return {}
    try:
        outer = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(outer, dict):
        return {}
    result: dict[str, dict[str, str]] = {}
    for key, payload in outer.items():
        key_str = str(key)
        if not key_str.startswith("custom:"):
            continue
        if isinstance(payload, dict):
            data = payload
        else:
            try:
                data = json.loads(str(payload))
            except json.JSONDecodeError:
                data = {"label": str(payload), "value": ""}
        if isinstance(data, dict):
            result[key_str] = {
                "label": str(data.get("label", "")).strip() or "Custom",
                "value": str(data.get("value", "")),
            }
    return result


def set_layout_storage(
    info: PostmapInfo,
    layout: list[dict[str, Any]],
    custom: dict[str, dict[str, str]],
) -> None:
    info.extra[LAYOUT_KEY] = json.dumps(layout, separators=(",", ":"))
    encoded = {
        key: json.dumps(value, separators=(",", ":"))
        for key, value in custom.items()
    }
    info.extra[CUSTOM_KEY] = json.dumps(encoded, separators=(",", ":"))


def new_custom_key() -> str:
    return f"custom:{uuid.uuid4().hex[:10]}"


def field_value(info: PostmapInfo, key: str, custom: dict[str, dict[str, str]] | None = None) -> str:
    if key.startswith("custom:"):
        fields = custom if custom is not None else get_custom_fields(info)
        return fields.get(key, {}).get("value", "")
    if key in READONLY_KEYS:
        return ""
    return str(getattr(info, key, "") or "")


def field_label(key: str, custom: dict[str, dict[str, str]] | None = None) -> str:
    if key.startswith("custom:"):
        fields = custom if custom is not None else {}
        return fields.get(key, {}).get("label", "Custom") or "Custom"
    return BUILTIN_LABELS.get(key, key.replace("_", " ").title())


def format_display_line(info: PostmapInfo, key: str, custom: dict[str, dict[str, str]] | None = None) -> str:
    if key == "crs_heading":
        return BUILTIN_LABELS["crs_heading"]
    if key.startswith("custom:"):
        label = field_label(key, custom)
        value = field_value(info, key, custom) or "—"
        return f"{label}: {value}"
    if key == "epsg_code":
        code = normalize_epsg(field_value(info, key))
        authority = epsg_label(code) if code else "—"
        return f"Authority: {authority}"
    if key == "crs_name":
        return f"Name: {field_value(info, key) or '—'}"
    label = BUILTIN_LABELS.get(key, key)
    value = field_value(info, key) or "—"
    return f"{label}: {value}"


def column_display_lines(
    info: PostmapInfo,
    column: int,
) -> list[str]:
    custom = get_custom_fields(info)
    layout = get_layout(info)
    lines: list[str] = []
    for entry in layout:
        if entry["column"] != column:
            continue
        key = entry["key"]
        lines.append(format_display_line(info, key, custom))
    return lines


def info_from_board(
    info: PostmapInfo,
    header: dict[str, str],
    layout: list[dict[str, Any]],
    field_values: dict[str, str],
    custom: dict[str, dict[str, str]],
) -> PostmapInfo:
    updated = PostmapInfo(
        company_name=info.company_name,
        title=info.title,
        job_number=field_values.get("job_number", info.job_number).strip(),
        client=header.get("client", info.client).strip(),
        area=header.get("area", info.area).strip(),
        project=header.get("project", info.project).strip(),
        client_ref=field_values.get("client_ref", info.client_ref).strip(),
        file_name=field_values.get("file_name", info.file_name).strip(),
        user_name=field_values.get("user_name", info.user_name).strip(),
        date=field_values.get("date", info.date).strip() or info.date,
        crs_name=field_values.get("crs_name", info.crs_name).strip(),
        projection=field_values.get("projection", info.projection).strip(),
        epsg_code=normalize_epsg(field_values.get("epsg_code", info.epsg_code).strip()),
        geographic_datum=field_values.get("geographic_datum", info.geographic_datum).strip(),
        spheroid=field_values.get("spheroid", info.spheroid).strip(),
        semi_major_axis=info.semi_major_axis,
        inverse_flattening=info.inverse_flattening,
        eccentricity=info.eccentricity,
        extra=dict(info.extra),
    )
    set_layout_storage(updated, layout, custom)
    return updated


def ensure_layout(info: PostmapInfo) -> None:
    if not _parse_layout(info.extra.get(LAYOUT_KEY, "")):
        set_layout_storage(info, list(DEFAULT_LAYOUT), get_custom_fields(info))
