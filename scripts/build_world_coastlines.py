"""Build simplified Natural Earth 50m coastlines for the offline minimap.

Downloads ne_50m_coastline.geojson (once) and writes xpostmaps/assets/world_coastlines.json.
Run: python scripts/build_world_coastlines.py
"""

from __future__ import annotations

import json
import math
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
    "geojson/ne_50m_coastline.geojson"
)
CACHE_PATH = ROOT / "data" / "ne_50m_coastline.geojson"
OUTPUT_PATH = ROOT / "xpostmaps" / "assets" / "world_coastlines.json"
# Degrees — ~2 km at mid-latitudes; enough detail for a 150px minimap when zoomed.
SIMPLIFY_EPSILON = 0.02


def _perp_distance(point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]) -> float:
    x0, y0 = start
    x1, y1 = end
    px, py = point
    dx = x1 - x0
    dy = y1 - y0
    if dx == 0.0 and dy == 0.0:
        return math.hypot(px - x0, py - y0)
    t = ((px - x0) * dx + (py - y0) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    proj_x = x0 + t * dx
    proj_y = y0 + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def simplify_line(points: list[list[float]], epsilon: float) -> list[list[float]]:
    if len(points) <= 2:
        return points

    def rdp(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
        if len(pts) < 3:
            return pts
        start, end = pts[0], pts[-1]
        max_dist = 0.0
        max_idx = 0
        for i in range(1, len(pts) - 1):
            dist = _perp_distance(pts[i], start, end)
            if dist > max_dist:
                max_dist = dist
                max_idx = i
        if max_dist > epsilon:
            left = rdp(pts[: max_idx + 1])
            right = rdp(pts[max_idx:])
            return left[:-1] + right
        return [start, end]

    tuples = [(float(p[0]), float(p[1])) for p in points]
    simplified = rdp(tuples)
    return [[lon, lat] for lon, lat in simplified]


def iter_linestrings(geojson: dict) -> list[list[list[float]]]:
    lines: list[list[list[float]]] = []
    for feature in geojson.get("features", []):
        geom = feature.get("geometry") or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates") or []
        if gtype == "LineString":
            lines.append(coords)
        elif gtype == "MultiLineString":
            lines.extend(coords)
    return lines


def download_source(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {SOURCE_URL} …")
    urllib.request.urlretrieve(SOURCE_URL, path)


def build() -> None:
    if not CACHE_PATH.is_file():
        download_source(CACHE_PATH)
    geojson = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    raw_lines = iter_linestrings(geojson)

    segments: list[dict] = []
    total_vertices = 0
    for line in raw_lines:
        if len(line) < 2:
            continue
        simplified = simplify_line(line, SIMPLIFY_EPSILON)
        if len(simplified) < 2:
            continue
        lons = [pt[0] for pt in simplified]
        lats = [pt[1] for pt in simplified]
        segments.append(
            {
                "b": [min(lons), min(lats), max(lons), max(lats)],
                "p": simplified,
            }
        )
        total_vertices += len(simplified)

    payload = {
        "source": "natural_earth_50m",
        "simplify_epsilon_deg": SIMPLIFY_EPSILON,
        "segments": segments,
        # Legacy key for any code expecting "lines"
        "lines": [seg["p"] for seg in segments],
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(
        f"Wrote {OUTPUT_PATH.name}: {len(segments)} segments, "
        f"{total_vertices:,} vertices, {size_kb:.0f} KB"
    )


if __name__ == "__main__":
    try:
        build()
    except Exception as exc:  # noqa: BLE001
        print(f"Failed: {exc}", file=sys.stderr)
        sys.exit(1)
