from pathlib import Path
from unittest.mock import patch

from xpostmaps.core.models import PreplotCatalogEntry
from xpostmaps.core.preplot_catalog_utils import (
    catalog_for_saved_files,
    refresh_preplot_catalog,
)


def test_preplot_catalog_for_saved_files_avoids_filesystem(tmp_path: Path) -> None:
    file_path = str(tmp_path / "survey.p190")
    saved = [
        PreplotCatalogEntry(
            preplot_number=1,
            file_path=file_path,
            crs_code="2193",
            total_lines=12,
            file_mtime_ns=123,
            file_size=456,
        )
    ]

    with patch("pathlib.Path.is_file") as is_file:
        catalog = catalog_for_saved_files([file_path], saved)

    is_file.assert_not_called()
    assert len(catalog) == 1


def test_refresh_preplot_catalog_reuses_unchanged_entry(tmp_path: Path) -> None:
    path = tmp_path / "survey.p190"
    path.write_text("placeholder\n", encoding="utf-8")
    stat = path.stat()
    saved = PreplotCatalogEntry(
        preplot_number=1,
        file_path=str(path),
        crs_code="2193",
        total_lines=3,
        file_mtime_ns=int(stat.st_mtime_ns),
        file_size=int(stat.st_size),
    )

    with patch(
        "xpostmaps.core.preplot_catalog_utils.build_preplot_catalog_entry"
    ) as build_entry:
        catalog = refresh_preplot_catalog([str(path)], [saved], force=False)

    build_entry.assert_not_called()
    assert catalog == [saved]
