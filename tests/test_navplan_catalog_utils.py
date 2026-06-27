from pathlib import Path
from unittest.mock import patch

from xpostmaps.core.models import NavplanCatalogEntry
from xpostmaps.core.navplan_catalog_utils import (
    build_navplan_catalog_entry,
    catalog_for_saved_files,
    refresh_navplan_catalog,
)


def test_catalog_for_saved_files_avoids_filesystem(tmp_path: Path) -> None:
    file_path = str(tmp_path / "0103643A.navplan")
    saved = [
        NavplanCatalogEntry(
            navplan_number=1,
            navplan_name="0103643A",
            line_direction="090°",
            file_path=file_path,
            crs_code="2193",
            fsp=100,
            lsp=200,
            total_points=101,
            file_mtime_ns=123,
            file_size=456,
        )
    ]

    with patch("pathlib.Path.is_file") as is_file:
        catalog = catalog_for_saved_files([file_path], saved)

    is_file.assert_not_called()
    assert len(catalog) == 1
    assert catalog[0].navplan_name == "0103643A"


def test_refresh_navplan_catalog_reuses_unchanged_entry(tmp_path: Path) -> None:
    path = tmp_path / "line.navplan"
    path.write_text("placeholder\n", encoding="utf-8")
    stat = path.stat()
    saved = NavplanCatalogEntry(
        navplan_number=1,
        navplan_name="Cached",
        file_path=str(path),
        crs_code="2193",
        file_mtime_ns=int(stat.st_mtime_ns),
        file_size=int(stat.st_size),
    )

    with patch(
        "xpostmaps.core.navplan_catalog_utils.build_navplan_catalog_entry"
    ) as build_entry:
        catalog = refresh_navplan_catalog([str(path)], [saved], force=False)

    build_entry.assert_not_called()
    assert catalog == [saved]


def test_refresh_navplan_catalog_reparses_modified_entry(tmp_path: Path) -> None:
    path = tmp_path / "line.navplan"
    path.write_text("placeholder\n", encoding="utf-8")
    saved = NavplanCatalogEntry(
        navplan_number=1,
        navplan_name="Stale",
        file_path=str(path),
        crs_code="2193",
        file_mtime_ns=1,
        file_size=1,
    )
    fresh = NavplanCatalogEntry(
        navplan_number=1,
        navplan_name="Fresh",
        file_path=str(path),
        crs_code="2193",
    )

    with patch(
        "xpostmaps.core.navplan_catalog_utils.build_navplan_catalog_entry",
        return_value=fresh,
    ) as build_entry:
        catalog = refresh_navplan_catalog([str(path)], [saved], force=False)

    build_entry.assert_called_once()
    assert catalog == [fresh]


def test_build_navplan_catalog_entry_records_fingerprint(tmp_path: Path) -> None:
    sample = Path("4D/4030/Navplans/Priority1/0103643A.navplan")
    if not sample.is_file():
        return

    entry = build_navplan_catalog_entry(sample)
    assert entry is not None
    assert entry.file_mtime_ns > 0
    assert entry.file_size > 0
