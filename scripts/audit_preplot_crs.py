"""Audit preplot CRS/EPSG parsing across 4D and sample files."""

from __future__ import annotations

from pathlib import Path

from xpostmaps.core.crs_utils import infer_epsg_from_header, pyproj_available
from xpostmaps.core.preplot_catalog_utils import build_preplot_catalog
from xpostmaps.parsers.metadata_parser import (
    _p190_grid_parameters,
    parse_file_metadata,
    parse_p111_metadata,
    parse_p190_metadata,
)


def collect_preplot_paths() -> list[Path]:
    roots = [Path("4D"), Path("Sample Preplots")]
    paths: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        paths.extend(root.rglob("Preplot/*"))
        for pattern in ("*.p190", "*.190", "*.p111"):
            paths.extend(root.glob(pattern))
    unique: list[Path] = []
    seen: set[str] = set()
    for path in sorted(paths):
        if not path.is_file():
            continue
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def audit_path(path: Path) -> dict:
    fmt = "p111" if path.suffix.lower() == ".p111" else "p190"
    meta = parse_file_metadata(path, fmt if path.suffix.lower() in (".p111", ".p190") else None)
    cm, fe, fn, sf = _p190_grid_parameters(meta) if fmt == "p190" else (None, None, None, None)
    inferred = ""
    if fmt == "p190":
        inferred = infer_epsg_from_header(
            meta.get("geographic datum", ""),
            meta.get("projection", ""),
            meta.get("projection zone", ""),
            central_meridian=cm,
            false_easting=fe,
            false_northing=fn,
            scale_factor=sf,
        )
    catalog = build_preplot_catalog([path])
    epsg = meta.get("epsg code", "")
    catalog_epsg = catalog[0].crs_code if catalog else ""
    return {
        "path": path,
        "fmt": fmt,
        "epsg": epsg,
        "inferred": inferred,
        "catalog": catalog_epsg,
        "datum": meta.get("geographic datum", meta.get("geodetic datum", "")),
        "projection": meta.get("projection", ""),
        "zone": meta.get("projection zone", ""),
        "crs_name": meta.get("crs name", ""),
    }


def main() -> None:
    print(f"pyproj available: {pyproj_available()}")
    print("=" * 100)
    rows = [audit_path(path) for path in collect_preplot_paths()]
    missing = [r for r in rows if not r["catalog"]]
    mismatches = [
        r
        for r in rows
        if r["inferred"] and r["epsg"] and r["inferred"] != r["epsg"]
    ]

    for row in rows:
        status = "OK" if row["catalog"] else "MISSING"
        if row["inferred"] and row["epsg"] and row["inferred"] != row["epsg"]:
            status = "MISMATCH"
        print(
            f"{status:8} [{row['fmt']:4}] {row['path'].name:42} "
            f"epsg={row['epsg'] or '-':6} catalog={row['catalog'] or '-':6} "
            f"inferred={row['inferred'] or '-'}"
        )
        if not row["catalog"] or status == "MISMATCH":
            print(f"         datum={row['datum']!r}")
            print(f"         projection={row['projection']!r} zone={row['zone']!r}")

    print("=" * 100)
    print(f"Total: {len(rows)}  Missing CRS: {len(missing)}  Explicit/inferred mismatch: {len(mismatches)}")


if __name__ == "__main__":
    main()
