"""Generate fixed-width P190 sample records for testing."""

from __future__ import annotations


def format_p190_s_record(
    line_name: str,
    vessel_id: str,
    source_id: str,
    point_num: int,
    lat: str,
    lon: str,
    x: float,
    y: float,
    depth: float,
) -> str:
    return (
        f"S{line_name:<12}"
        f"   {vessel_id}{source_id} "
        f"{point_num:6d}"
        f"{lat:>10}"
        f"{lon:>11}"
        f"{x:9.3f}"
        f"{y:9.3f}"
        f"{depth:6.1f}"
    )


def format_p190_v_record(
    line_name: str,
    vessel_id: str,
    source_id: str,
    point_num: int,
    lat: str,
    lon: str,
    x: float,
    y: float,
    depth: float,
) -> str:
    return (
        f"V{line_name:<12}"
        f"   {vessel_id}{source_id} "
        f"{point_num:6d}"
        f"{lat:>10}"
        f"{lon:>11}"
        f"{x:9.3f}"
        f"{y:9.3f}"
        f"{depth:6.1f}"
    )
