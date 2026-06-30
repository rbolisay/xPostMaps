"""Verify bundled runtime imports and assets before launching the GUI."""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path


def _require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Missing bundled {label}: {path}")


def _require_json(path: Path, label: str) -> None:
    _require_file(path, label)
    json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    app_root = Path(__file__).resolve().parent
    os.chdir(app_root)
    app_root_str = str(app_root)
    if app_root_str not in sys.path:
        sys.path.insert(0, app_root_str)

    _require_file(app_root / "TierMaps_No_bg.png", "application logo")
    _require_file(app_root / "TierMaps_Logo.png", "PDF logo")
    _require_file(app_root / "TierMaps_Logo_grey.png", "PDF grey logo")
    _require_file(app_root / "TierMaps.png", "fallback logo")
    _require_json(app_root / "xpostmaps" / "assets" / "world_coastlines.json", "coastline data")
    _require_json(app_root / "xpostmaps" / "assets" / "world_land_polygons.json", "land polygon data")

    python_home = app_root / "python"
    site = python_home / "Lib" / "site-packages"
    for rel in (
        "pythonw.exe",
        "Lib/site-packages/PySide6/plugins/platforms/qwindows.dll",
        "Lib/site-packages/pyproj/proj_dir/share/proj/proj.db",
        "Lib/site-packages/llvmlite/binding/llvmlite.dll",
    ):
        _require_file(python_home / Path(*rel.split("/")), f"runtime file ({rel})")

    import fitz  # noqa: F401
    import ezdxf  # noqa: F401
    import numba  # noqa: F401
    import numpy  # noqa: F401
    import OpenGL  # noqa: F401
    import pyproj  # noqa: F401
    import pyqtgraph  # noqa: F401
    import shapefile  # noqa: F401
    from PySide6.QtWidgets import QApplication

    from pyproj import CRS

    CRS.from_epsg(4326)

    from xpostmaps.ui.main_window import MainWindow

    app = QApplication([])
    MainWindow()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1) from None
