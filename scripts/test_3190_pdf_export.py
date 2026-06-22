"""Export a PDF from 3190.db and verify map + minimap are not empty."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import QApplication

from xpostmaps.core.database import Database
from xpostmaps.core.models import DisplayMode
from xpostmaps.core.pdf_export import PdfExportOptions, capture_export_images, compose_pdf_vector_from_captures
from xpostmaps.ui.map_widget import PostplotMapWidget
from xpostmaps.ui.right_pane import RightPane


def _find_db() -> Path | None:
    candidates = [
        ROOT / "data" / "3190.db",
        ROOT / "data" / "3190" / "3190.db",
        Path(r"C:\xPostMaps\data\3190.db"),
    ]
    data_dir = ROOT / "data"
    if data_dir.is_dir():
        candidates.extend(sorted(data_dir.glob("*3190*.db")))
    for path in candidates:
        if path.is_file():
            return path
    return None


def _wait_until(app: QApplication, predicate, *, timeout_s: float = 120.0) -> bool:
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _non_blank_ratio(image: QImage, *, sample_step: int = 8) -> float:
    """Fraction of sampled pixels that differ from the corners (likely has content)."""
    if image.isNull() or image.width() < 2 or image.height() < 2:
        return 0.0
    ref = image.pixelColor(0, 0)
    different = 0
    total = 0
    for y in range(0, image.height(), sample_step):
        for x in range(0, image.width(), sample_step):
            total += 1
            if image.pixelColor(x, y) != ref:
                different += 1
    return different / max(total, 1)


def main() -> None:
    db_path = _find_db()
    if db_path is None:
        print("3190.db not found under data/ — place it at data/3190.db and re-run.")
        sys.exit(1)

    out_dir = ROOT / "output" / "pdf_tests"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "3190_export_test.pdf"

    db = Database(db_path)
    projects = db.list_projects()
    if not projects:
        print("No projects in database.")
        sys.exit(1)
    project_name = projects[0]
    print(f"Loading {project_name} from {db_path.name}…")

    settings, map_data = db.load_project(project_name, with_positions=False)
    app = QApplication.instance() or QApplication(sys.argv)
    map_widget = PostplotMapWidget()
    right_pane = RightPane()
    map_widget.resize(1200, 800)
    right_pane.setFixedWidth(RightPane._BASE_WIDTH)
    map_widget.set_legend(settings.legend_config)
    map_widget.set_display_mode(settings.display_mode)
    map_widget.show()
    right_pane.show()

    map_widget.render(map_data, force=True)
    map_widget.restore_view(settings.map_view)
    app.processEvents()

    _wait_until(app, map_widget._gl_layers_ready, timeout_s=120.0)
    map_widget._finish_pan_interaction()
    map_widget._on_gl_view_settled()
    map_widget._apply_view_clip()
    _wait_until(app, lambda: not map_widget._interacting, timeout_s=15.0)
    app.processEvents()

    right_pane.update_from_project(settings, map_data)
    app.processEvents()

    opts = PdfExportOptions(
        output_dir=out_dir,
        filename=out_path.name,
        paper="A2",
        dpi=300,
        landscape=True,
    )

    map_image, pane_image = capture_export_images(map_widget, right_pane, opts)
    map_ratio = _non_blank_ratio(map_image)
    pane_ratio = _non_blank_ratio(pane_image)
    print(f"Map capture non-blank ratio: {map_ratio:.3f}")
    print(f"Pane capture non-blank ratio: {pane_ratio:.3f}")

    map_image.save(str(out_dir / "3190_map_capture.png"))
    pane_image.save(str(out_dir / "3190_pane_capture.png"))

    compose_pdf_vector_from_captures(out_path, map_image, pane_image, opts)
    doc = QPdfDocument()
    doc.load(str(out_path))
    preview = doc.render(0, QSize(1600, 1130))
    preview.save(str(out_dir / "3190_export_preview.png"))
    print(f"Saved PDF: {out_path} ({out_path.stat().st_size / 1024 / 1024:.2f} MB)")

    if map_ratio < 0.02:
        print("FAIL: map capture looks empty")
        sys.exit(2)
    if pane_ratio < 0.05:
        print("FAIL: pane capture looks empty")
        sys.exit(2)
    print("OK: map and pane captures contain visible content")


if __name__ == "__main__":
    main()
