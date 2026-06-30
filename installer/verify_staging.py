"""Build-time verification that installer staging is complete and self-contained."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REQUIRED_ROOT_FILES = (
    "run.py",
    "preflight.py",
    "TierMaps.bat",
    "TierMaps.ico",
    "TierMaps.png",
    "TierMaps_No_bg.png",
    "TierMaps_Logo.png",
    "TierMaps_Logo_grey.png",
    "requirements.txt",
)

REQUIRED_ASSETS = (
    "xpostmaps/assets/world_coastlines.json",
    "xpostmaps/assets/world_land_polygons.json",
)

REQUIRED_PACKAGES = (
    "PySide6",
    "pyqtgraph",
    "numpy",
    "numba",
    "llvmlite",
    "pyproj",
    "shapefile.py",
    "ezdxf",
    "OpenGL",
    "fitz",
    "shiboken6",
)

REQUIRED_NATIVE = (
    "python/python.exe",
    "python/pythonw.exe",
    "python/Lib/site-packages/PySide6/plugins/platforms/qwindows.dll",
    "python/Lib/site-packages/shiboken6/shiboken6.abi3.dll",
    "python/Lib/site-packages/llvmlite/binding/llvmlite.dll",
    "python/Lib/site-packages/pyproj/proj_dir/share/proj/proj.db",
)

MIN_ASSET_BYTES = {
    "xpostmaps/assets/world_coastlines.json": 1024,
    "xpostmaps/assets/world_land_polygons.json": 1024,
    "TierMaps_No_bg.png": 512,
    "TierMaps_Logo.png": 512,
}


def verify(staging: Path) -> list[str]:
    errors: list[str] = []

    for rel in REQUIRED_ROOT_FILES:
        path = staging / rel
        if not path.is_file():
            errors.append(f"missing file: {rel}")

    for rel in REQUIRED_ASSETS:
        path = staging / rel
        if not path.is_file():
            errors.append(f"missing asset: {rel}")
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid json: {rel}: {exc}")

    for rel, minimum in MIN_ASSET_BYTES.items():
        path = staging / rel
        if path.is_file() and path.stat().st_size < minimum:
            errors.append(f"asset too small: {rel} ({path.stat().st_size} bytes)")

    site = staging / "python" / "Lib" / "site-packages"
    for pkg in REQUIRED_PACKAGES:
        if not (site / pkg).exists():
            errors.append(f"missing package: {pkg}")

    for rel in REQUIRED_NATIVE:
        if not (staging / rel).is_file():
            errors.append(f"missing native runtime: {rel}")

    settings = staging / "data" / "settings.json"
    if settings.is_file():
        try:
            data = json.loads(settings.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid settings.json: {exc}")
        else:
            for key in ("db_directory", "pdf_output_directory"):
                value = str(data.get(key, "")).strip()
                if value and ("xPostMaps" in value or "xpostmaps" in value.lower()):
                    errors.append(f"settings.json must not reference dev paths ({key})")

    return errors


def main() -> int:
    staging = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else (
        Path(__file__).resolve().parents[1] / "installer" / "staging"
    )
    if not staging.is_dir():
        print(f"ERROR: staging folder not found: {staging}", file=sys.stderr)
        return 1

    errors = verify(staging)
    if errors:
        print("Bundle verification failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    total = (
        len(REQUIRED_ROOT_FILES)
        + len(REQUIRED_ASSETS)
        + len(REQUIRED_PACKAGES)
        + len(REQUIRED_NATIVE)
    )
    print(f"Bundle verification passed ({total} checks).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
